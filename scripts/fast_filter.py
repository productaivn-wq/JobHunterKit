import json
import re
import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.db_client import get_connection

# Reconfigure standard output streams to use utf-8 encoding
if sys.stdout:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr:
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def should_exclude(title: str, jd_text: str, location: str = "") -> tuple[bool, str]:
    from core.company_extractor import is_jd_text_expired

    is_expired, expire_reason = is_jd_text_expired(jd_text, title)
    if is_expired:
        return True, f"Excluded: Closed/Expired JD ({expire_reason})"

    title_lower = title.lower()

    # Tokens split by non-alphanumeric characters
    tokens = set(re.findall(r"[a-z0-9]+", title_lower))

    # 1. Check senior level / target roles (including Product Owner, PM, CPO, Lead, Director, etc.)
    target_role_words = {
        "manager",
        "director",
        "head",
        "chief",
        "vp",
        "lead",
        "leader",
        "leadership",
        "principal",
        "cto",
        "cpo",
        "architect",
        "strategist",
        "founder",
        "ceo",
        "co-founder",
        "owner",
        "po",
        "pm",
        "senior",
        "sr",
        "expert",
        "specialist",
        "lead",
        "consultant",
        # AI & Agentic leadership tokens
        "builder",
        "agentic",
        "agent",
        "fde",
        # Vietnamese seniority & leadership tokens
        "truong",
        "quan",
        "giam",
        "chuyen",
        "chủ",
        "trưởng",
        "quản",
        "giám",
        "chuyên",
    }
    is_target_seniority = any(w in tokens for w in target_role_words) or any(
        phrase in title_lower
        for phrase in [
            "product owner",
            "product manager",
            "product lead",
            "product director",
            "product builder",
            "forward deployed",
            "agentic engineer",
            "ai engineer",
            "ai native",
            "ai lead",
            "ai manager",
            "ai architect",
            "ai product",
            "ai systems",
            "quản lý sản phẩm",
            "giám đốc sản phẩm",
            "trưởng nhóm",
            "chuyên viên cao cấp",
            "chuyên viên quản lý",
            "chuyên viên",
            "quản trị dự án",
            "quản lý dự án",
            "project manager",
            "program manager",
        ]
    )

    # Obvious low-seniority exclusions
    exclude_words = {
        "intern",
        "internship",
        "trainee",
        "fresh",
        "fresher",
        "entry",
        "junior",
        "assistant",
        "student",
        "coop",
        "co-op",
        "internships",
        "associate",
        "officer",
        "exec",
        "executive",  # unless it's executive director/vp/etc.
    }

    # Handle C-level titles containing "officer" (e.g. Chief Product Officer, Chief Technology Officer)
    if "officer" in tokens:
        has_c_level = any(
            w in tokens
            for w in {
                "chief",
                "cpo",
                "cto",
                "ceo",
                "cio",
                "cso",
                "cdo",
                "head",
                "director",
                "principal",
            }
        )
        if has_c_level:
            exclude_words = exclude_words - {"officer"}

    # Handle "executive" special case: e.g. "Account Executive" or "Executive Assistant"
    if "executive" in tokens:
        # Check if it has a high seniority word
        has_high = any(
            w in tokens
            for w in {"director", "vp", "chief", "head", "cto", "cpo", "president"}
        )
        if not has_high:
            return (
                True,
                "Excluded: 'executive' without director/vp/chief/head/cto/cpo/president (usually sales or support role)",
            )
        else:
            exclude_words = exclude_words - {"exec", "executive"}

    has_exclusion = any(w in tokens for w in exclude_words)
    if has_exclusion:
        matched = [w for w in exclude_words if w in tokens]
        return True, f"Excluded: Low seniority keywords found: {matched}"

    # If it is not target seniority (e.g. doesn't have manager, director, head, lead, vp, owner, etc.)
    if not is_target_seniority:
        return (
            True,
            "Excluded: Title lacks senior/target role keywords (manager, director, head, chief, vp, lead, principal, cto, cpo, owner, architect, strategist, specialist, builder, agentic)",
        )

    # 2. Check tech lead / developer / hands-on engineering exclusions
    dev_words = {
        "developer",
        "programmer",
        "coder",
        "backend",
        "frontend",
        "fullstack",
        "software",
        "engineer",
        "eng",
        "qa",
        "tester",
        "testing",
        "sre",
        "devops",
        "infrastructure",
        "platform",
        "sysadmin",
        "administrator",
        "support",
        "helpdesk",
        "technician",
    }
    has_dev = any(w in tokens for w in dev_words)
    if has_dev:
        # Exceptions: if title explicitly mentions "architect", "prompt", "product", "agentic", "agent", "fde", or "ai"
        is_exception = (
            any(w in tokens for w in {"architect", "prompt", "product", "agentic", "agent", "fde", "ai"})
            or any(
                phrase in title_lower
                for phrase in [
                    "product manager",
                    "product builder",
                    "forward deployed",
                    "agentic engineer",
                    "ai engineer",
                    "ai lead",
                    "ai product",
                    "ai systems",
                ]
            )
        )
        if not is_exception:
            matched = [w for w in dev_words if w in tokens]
            return (
                True,
                f"Excluded: Hands-on engineering/developer/support keywords found: {matched}",
            )

    # Exclude tech lead / technical lead / engineering lead / team lead
    if "lead" in tokens and any(
        w in tokens
        for w in {
            "tech",
            "technical",
            "engineering",
            "development",
            "developer",
            "software",
            "qa",
            "test",
            "support",
        }
    ):
        # Unless it is "Product Lead" or "AI Lead" or "Lead Architect" or "Lead Product Manager"
        is_exception = any(
            w in tokens for w in {"product", "ai", "architect", "strategist"}
        )
        if not is_exception:
            return (
                True,
                "Excluded: Tech Lead / Engineering Lead / Team Lead role (candidate excludes hands-on/tech-lead roles)",
            )

    # 3. Check domain/function exclusions (marketing, sales, HR, recruiting, finance, content, designer, customer success)
    domain_exclude_words = {
        "marketing",
        "sales",
        "recruiter",
        "recruiting",
        "hr",
        "talent",
        "account",  # Account Manager, Account Executive, etc.
        "customer",  # Customer Success, Customer Support, etc.
        "success",
        "support",
        "content",
        "copywriter",
        "writer",
        "designer",
        "ux",
        "ui",
        "design",
        "finance",
        "financial",
        "accountant",
        "accounting",
        "bookkeeper",
        "auditor",
        "legal",
        "lawyer",
        "compliance",
        "analyst",  # Data Analyst, Business Analyst, etc. unless Product or AI is present
    }

    has_domain_exclude = any(w in tokens for w in domain_exclude_words)
    if has_domain_exclude:
        # Exception: if it's "Product Manager" or "AI/ML Product" or "Product Director" or "Product Owner"
        is_pm_exception = "product" in tokens or "ai" in tokens or "ml" in tokens
        if not is_pm_exception:
            matched = [w for w in domain_exclude_words if w in tokens]
            return True, f"Excluded: Domain/Function mismatch keywords found: {matched}"

    # 4. Check salary explicitly in JD text
    # If the JD mentions a monthly salary like "1000$", "2000$", "2500$", "3000$", etc.
    # or "50 triệu", "60 triệu", "70 triệu" (less than 3500 * 25k = 87.5M)
    # Let's write a simple regex or check.
    # For now, let's keep it safe. If salary is mentioned and clearly below $3500 net, we could exclude it.

    return False, ""


def run_filter():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, company, location, jd_text
                FROM job_hunter.jobs
                WHERE status_score = 'pending'
                ORDER BY scraped_at DESC;
                """
            )
            jobs = cur.fetchall()
            print(f"Loaded {len(jobs)} pending jobs.")

            skipped_count = 0
            for row in jobs:
                job_id, title, company, location, jd_text = row
                exclude, reason = should_exclude(title, jd_text)
                if exclude:
                    # Update status in DB
                    cur.execute(
                        "UPDATE job_hunter.jobs SET status_score = 'completed', status_apply = 'skipped' WHERE id = %s;",
                        (job_id,),
                    )
                    # Insert score audit
                    rubric_used = {"is_irrelevant": True}
                    cur.execute(
                        """
                        INSERT INTO job_hunter.scores (job_id, match_score, reasoning, rubric_used, top_strengths, key_gaps)
                        VALUES (%s, %s, %s, %s, %s, %s);
                        """,
                        (
                            job_id,
                            0,
                            reason,
                            json.dumps(rubric_used),
                            json.dumps([]),
                            json.dumps([reason]),
                        ),
                    )
                    try:
                        print(
                            f"Skipped job {job_id}: '{title}' at '{company}' -> {reason}"
                        )
                    except Exception:
                        # Fallback for encoding issues
                        safe_title = title.encode("ascii", errors="replace").decode(
                            "ascii"
                        )
                        safe_company = company.encode("ascii", errors="replace").decode(
                            "ascii"
                        )
                        safe_reason = reason.encode("ascii", errors="replace").decode(
                            "ascii"
                        )
                        print(
                            f"Skipped job {job_id}: '{safe_title}' at '{safe_company}' -> {safe_reason}"
                        )
                    skipped_count += 1

            conn.commit()
            print(
                f"Filter run completed. Total jobs skipped: {skipped_count}/{len(jobs)}"
            )
    except Exception as e:
        print(f"Error during filtering: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    run_filter()
