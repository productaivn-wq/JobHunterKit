"""
Cleanup script to backfill 'Unknown Company' fields and remove expired jobs from application queues in job_hunter.jobs.
"""

import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.company_extractor import extract_company_name, is_jd_text_expired
from core.db_client import get_connection


def cleanup_database() -> None:
    """Performs database maintenance cleaning expired postings and resolving unknown company metadata."""
    print("=== Database Audit & Cleanup: Expired Jobs & Unknown Companies ===")
    conn = get_connection()
    try:
        # 1. Backfill 'Unknown Company'
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, company, url, jd_text
                FROM job_hunter.jobs
                WHERE company IS NULL OR company = '' OR company = 'Unknown Company';
            """)
            unknown_jobs = cur.fetchall()

        print(
            f"Found {len(unknown_jobs)} jobs with missing or 'Unknown Company'. Processing..."
        )
        updated_company_count = 0

        # Boot playwright context if needed for live page inspection fallback
        browser = None
        playwright_obj = None
        page = None

        try:
            with conn.cursor() as cur:
                for job_id, title, company, url, jd_text in unknown_jobs:
                    extracted = extract_company_name(
                        jd_text=jd_text or "",
                        page_title=title or "",
                        page_url=url or "",
                    )
                    new_title = None

                    if (
                        (not extracted or extracted == "Unknown Company")
                        and url
                        and url.startswith("http")
                    ):
                        if not browser:
                            try:
                                from playwright.sync_api import sync_playwright
                                from playwright_stealth import Stealth

                                playwright_obj = sync_playwright().start()
                                browser = playwright_obj.chromium.launch(
                                    headless=True, channel="chrome"
                                )
                                context = browser.new_context(
                                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                                )
                                page = context.new_page()
                                Stealth().apply_stealth_sync(page)
                            except Exception as pw_err:
                                print(
                                    f"  [WARN] Failed to start Playwright for live page inspection: {pw_err}"
                                )

                        if page:
                            try:
                                print(f"  [INSPECTING URL] Job {job_id}: {url}")
                                page.goto(
                                    url, wait_until="domcontentloaded", timeout=25000
                                )
                                p_title = page.title()
                                extracted = extract_company_name(
                                    jd_text=jd_text or "",
                                    page_title=p_title,
                                    page_url=url,
                                    page=page,
                                )
                                if not title or title == "Unknown Title":
                                    h1_el = page.locator("h1").first
                                    if h1_el.count() > 0 and h1_el.inner_text().strip():
                                        new_title = h1_el.inner_text().strip()
                                    elif p_title:
                                        import re

                                        m = re.search(
                                            r"^(?:Tuyển\s+)?(.*?)(?:\s+làm việc\s+tại|\s+tại|\s*[\-\|]|\s*$)",
                                            p_title,
                                            re.IGNORECASE,
                                        )
                                        if m and m.group(1).strip():
                                            new_title = m.group(1).strip()
                            except Exception as fetch_err:
                                print(f"  [WARN] Failed to fetch {url}: {fetch_err}")

                    if extracted and extracted != "Unknown Company":
                        if new_title:
                            cur.execute(
                                "UPDATE job_hunter.jobs SET company = %s, title = %s WHERE id = %s;",
                                (extracted, new_title, job_id),
                            )
                            print(
                                f"  [FIXED COMPANY & TITLE] Job {job_id}: Title: '{new_title}' | Company: '{extracted}'"
                            )
                        else:
                            cur.execute(
                                "UPDATE job_hunter.jobs SET company = %s WHERE id = %s;",
                                (extracted, job_id),
                            )
                            print(
                                f"  [FIXED COMPANY] Job {job_id}: '{title}' => Company: '{extracted}'"
                            )
                        updated_company_count += 1
            conn.commit()
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if playwright_obj:
                try:
                    playwright_obj.stop()
                except Exception:
                    pass

        print(f"Backfilled company names for {updated_company_count} jobs.")

        # 2. Check and skip expired jobs in pending/applying queues
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, company, status_apply, status_score, jd_text
                FROM job_hunter.jobs
                WHERE status_apply IN ('pending', 'applying', 'needs_manual_intervention');
            """)
            active_jobs = cur.fetchall()

        print(
            f"\nFound {len(active_jobs)} jobs in active queues. Checking for expired signatures..."
        )
        expired_count = 0

        with conn.cursor() as cur:
            for (
                job_id,
                title,
                company,
                status_apply,
                status_score,
                jd_text,
            ) in active_jobs:
                is_expired, reason = is_jd_text_expired(jd_text or "", title or "")
                if is_expired:
                    cur.execute(
                        """
                        UPDATE job_hunter.jobs
                        SET status_apply = 'skipped', status_score = 'skipped_expired'
                        WHERE id = %s;
                    """,
                        (job_id,),
                    )
                    expired_count += 1
                    print(
                        f"  [SKIPPED EXPIRED] Job {job_id} ({company} - {title}): {reason}"
                    )
        conn.commit()
        print(f"Moved {expired_count} expired jobs to status_apply = 'skipped'.")

        # 3. Check and skip irrelevant domain jobs (Tax, Accounting, ALM, Construction, etc.) in active queues
        from fast_filter import should_exclude

        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, company, status_apply, status_score, jd_text
                FROM job_hunter.jobs
                WHERE status_apply IN ('pending', 'applying', 'needs_manual_intervention');
            """)
            active_jobs_domain = cur.fetchall()

        print(
            f"\nFound {len(active_jobs_domain)} jobs in active queues. Checking for irrelevant domain/title signatures..."
        )
        irrelevant_count = 0

        with conn.cursor() as cur:
            for (
                job_id,
                title,
                company,
                status_apply,
                status_score,
                jd_text,
            ) in active_jobs_domain:
                excl, reason = should_exclude(title or "", jd_text or "", company or "")
                if excl:
                    cur.execute(
                        """
                        UPDATE job_hunter.jobs
                        SET status_apply = 'skipped', status_score = 'skipped_prefilter'
                        WHERE id = %s;
                    """,
                        (job_id,),
                    )
                    irrelevant_count += 1
                    print(
                        f"  [SKIPPED IRRELEVANT] Job {job_id} ({company} - {title}): {reason}"
                    )
        conn.commit()
        print(
            f"Moved {irrelevant_count} irrelevant domain/title jobs to status_apply = 'skipped'."
        )

    except Exception as e:
        print(f"[ERROR] Database cleanup failed: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    cleanup_database()
