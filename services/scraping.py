import json
import time
import urllib.parse

from services.common import (
    LINKEDIN_COLLECTIONS,
    PLAYWRIGHT_AVAILABLE,
    _boot_playwright_context,
    _load_excluded_companies,
    _preload_applied_history_sets,
)

if PLAYWRIGHT_AVAILABLE:
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth


def _detect_and_log_external_channel(page, source_url):
    """Inspects page for external apply button and registers new channels/domains."""
    try:
        # Run JS to find the apply link href or detect button type
        link_data = page.evaluate("""() => {
            const link = document.querySelector('a.jobs-apply-button, a[href*="/jobs/view/externalApply/"], a.base-card__full-link, .jobs-s-apply a');
            if (link && link.href) {
                return { type: 'link', href: link.href };
            }
            const btn = document.querySelector('button.jobs-apply-button, .jobs-s-apply button');
            if (btn) {
                const txt = btn.innerText.trim().toLowerCase();
                if (txt.includes('easy apply') || txt.includes('đơn giản') || txt.includes('dễ dàng')) {
                    return { type: 'easy_apply', href: null };
                }
                return { type: 'external_button', href: null };
            }
            return null;
        }""")

        if not link_data or not link_data.get("href"):
            return

        href = link_data["href"]
        if not href.startswith("http"):
            return

        import requests

        final_url = href
        # If it's a LinkedIn externalApply redirect, resolve it in background
        if (
            "linkedin.com/jobs/view/externalApply/" in href
            or "linkedin.com/jobs/view/" in href
        ):
            try:
                r = requests.head(href, allow_redirects=True, timeout=5)
                final_url = r.url
            except:
                try:
                    r = requests.get(href, allow_redirects=True, timeout=5, stream=True)
                    final_url = r.url
                except:
                    pass

        parsed = urllib.parse.urlparse(final_url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        if not domain or domain in ["linkedin.com", "link"]:
            return

        # Check if domain is in our known direct scraper lists
        known_domains = [
            "linkedin.com",
            "indeed.com",
            "itviec.com",
            "topcv.vn",
            "careerjet.vn",
            "vietnamworks.com",
            "glints.com",
        ]
        if any(kd in domain for kd in known_domains):
            return

        print(
            f"  [CHANNEL DISCOVERY] Detected new external portal domain: {domain} (from {final_url})"
        )
        from core.db_client import get_connection

        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job_hunter.discovered_channels (domain, example_url)
                VALUES (%s, %s)
                ON CONFLICT (domain) DO NOTHING;
            """,
                (domain, final_url),
            )
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"  [CHANNEL DISCOVERY WARNING] Failed to discover channel: {e}")


def _fetch_jd_text(browser, url):
    """Fetches job description text from a job page."""
    page = browser.new_page()
    Stealth().apply_stealth_sync(page)
    jd_text = ""
    try:
        page.goto(url, wait_until="commit", timeout=60000)

        # Detect and log external channel redirects
        _detect_and_log_external_channel(page, url)

        for selector in ["#job-details", ".show-more-less-html__markup", "main"]:
            try:
                page.wait_for_selector(selector, timeout=2000)
                jd_text = page.locator(selector).inner_text().strip()
                if jd_text and len(jd_text) > 50:
                    break
            except:
                pass
        if not jd_text or len(jd_text) < 50:
            jd_text = page.evaluate("document.body.innerText")
    except Exception as e:
        print(f"  [WARNING] Could not fetch description from {url}. Error: {e}")
        jd_text = "Description unavailable."
    finally:
        page.close()
    return jd_text


def _extract_card_info(card):
    """Extracts title, company, and url from a card locator."""
    title_elem = card.locator(
        "a.job-card-container__link strong, .job-card-list__title strong, .base-search-card__title"
    )
    title = (
        title_elem.first.inner_text().strip()
        if title_elem.count() > 0
        else "Unknown Title"
    )

    company_elem = card.locator(
        ".artdeco-entity-lockup__subtitle span, .job-card-container__primary-description, .base-search-card__subtitle"
    )
    company = (
        company_elem.first.inner_text().strip()
        if company_elem.count() > 0
        else "Unknown Company"
    )

    url_elem = card.locator(
        'a.base-card__full-link, a.job-card-container__link, a.job-card-list__title, a[href*="/jobs/view/"]'
    )
    url = url_elem.first.get_attribute("href") if url_elem.count() > 0 else "No URL"

    if url == "No URL":
        url_elem = card.locator("a").first
        if url_elem.count() > 0:
            url = url_elem.get_attribute("href")
            if url and not url.startswith("http"):
                url = "https://www.linkedin.com" + url
    elif not url.startswith("http"):
        url = "https://www.linkedin.com" + url

    return title, company, url


def _process_scraped_card(
    card,
    browser,
    jobs,
    seen_urls,
    seen_companies,
    already_submitted_urls=None,
    already_submitted_keys=None,
):
    """Processes a single job card, fetches its JD, and appends to jobs if valid."""
    title, company, url = _extract_card_info(card)
    if url == "No URL":
        return

    excluded = _load_excluded_companies()
    if company.strip().lower() in excluded:
        print(f"  [BLACKLIST] Skipping job from excluded company: {title} at {company}")
        return

    clean_url = url.split("?")[0].strip()
    clean_url_lower = clean_url.lower()
    dedup_key = f"{title.strip()} @ {company.strip()}".lower()

    if clean_url_lower in seen_urls or dedup_key in seen_companies:
        print(f"  [DEDUP] Skipping duplicate job during scraping: {title} at {company}")
        return

    if already_submitted_urls and clean_url_lower in already_submitted_urls:
        print(
            f"  [APPLIED] Skipping historically applied job by URL: {title} at {company}"
        )
        return

    if already_submitted_keys and dedup_key in already_submitted_keys:
        print(
            f"  [APPLIED] Skipping historically applied job by Key: {title} at {company}"
        )
        return

    seen_urls.add(clean_url_lower)
    seen_companies.add(dedup_key)

    jd_text = _fetch_jd_text(browser, url)
    if jd_text and len(jd_text) > 20:
        jobs.append(
            {
                "id": f"job_{len(jobs)}",
                "title": title,
                "company": company,
                "jd_text": jd_text,
                "url": url,
            }
        )
        print(f"  Scraped: {title} at {company}")


def live_linkedin_scrape(
    keyword,
    location,
    dirs,
    limit=50,
    state_file=None,
    date_posted="week",
    source="linkedin",
    cli_mode: bool = False,
):
    """Uses Playwright (authenticated Chrome) to scrape live LinkedIn job postings with pagination and multi-keyword loop. (UC-002)"""
    print("[UTOP|func|live_linkedin_scrape|cp-fr-005]")

    if not PLAYWRIGHT_AVAILABLE:
        print("  [ERROR] Playwright not available. Cannot scrape.")
        return None

    # Gate dedup-history reads behind cli_mode: DB-queue mode uses Postgres-level dedup instead.
    if cli_mode:
        already_submitted_keys, already_submitted_urls = _preload_applied_history_sets(
            dirs
        )
    else:
        already_submitted_keys, already_submitted_urls = set(), set()

    jobs_file = dirs.get("jobs_file") if dirs else None

    # Parse comma-separated keywords
    keywords_list = [k.strip() for k in keyword.split(",") if k.strip()]
    if not keywords_list:
        keywords_list = [keyword]

    print(
        f"[Phase 1: Search] Scraping live LinkedIn jobs for keywords: {keywords_list} in '{location}' with date filter '{date_posted}'..."
    )

    all_jobs = []
    seen_job_keys = set()
    seen_urls = set()
    seen_companies = set()

    collection_url = LINKEDIN_COLLECTIONS.get(source.lower())

    browser = None
    try:
        with sync_playwright() as p:
            try:
                print(
                    "  Booting authenticated Chrome browser for multi-search scraping..."
                )
                browser, context = _boot_playwright_context(p, state_file)
                page = context.new_page()
                Stealth().apply_stealth_sync(page)

                for kw in keywords_list:
                    print(f"\n  --- Scraping keyword: '{kw}' ---")
                    encoded_keyword = urllib.parse.quote(kw)
                    encoded_location = urllib.parse.quote(location)

                    date_filter = ""
                    if date_posted == "day":
                        date_filter = "&f_TPR=r86400"
                    elif date_posted == "week":
                        date_filter = "&f_TPR=r604800"
                    elif date_posted == "month":
                        date_filter = "&f_TPR=r2592000"

                    jobs_per_keyword = []
                    max_start = max(25, limit)
                    consecutive_no_new_pages = 0

                    for start in range(0, max_start, 25):
                        if len(jobs_per_keyword) >= limit:
                            break

                        if kw.startswith("http://") or kw.startswith("https://"):
                            # Use direct URL but handle pagination start parameter
                            if "?" in kw:
                                import re

                                base_url = re.sub(r"[&?]start=\\d+", "", kw)
                                connector = "&" if "?" in base_url else "?"
                                search_url = f"{base_url}{connector}start={start}"
                            else:
                                search_url = f"{kw}?start={start}"
                        else:
                            base_search_url = (
                                collection_url
                                if collection_url
                                else "https://www.linkedin.com/jobs/search"
                            )
                            connector = "&" if "?" in base_search_url else "?"
                            params = []
                            if kw:
                                params.append(f"keywords={encoded_keyword}")
                            if location:
                                params.append(f"location={encoded_location}")
                            if date_filter:
                                params.append(date_filter.lstrip("&"))
                            params.append(f"start={start}")
                            search_url = (
                                f"{base_search_url}{connector}{'&'.join(params)}"
                            )
                        print(f"    Navigating to page start={start}...")

                        try:
                            page.goto(search_url, wait_until="commit", timeout=60000)
                            page.wait_for_selector(
                                ".base-search-card, .job-card-container, [data-occludable-job-id], .jobs-search-results-list__item",
                                timeout=30000,
                            )

                            # Scroll 3 times per pagination page
                            for _ in range(3):
                                page.evaluate("""() => {
                                    window.scrollTo(0, document.body.scrollHeight);
                                    const containers = document.querySelectorAll('.jobs-search-results-list, .jobs-search-results, [class*="results-list"], [class*="scrollable"]');
                                    containers.forEach(el => {
                                        el.scrollTop = el.scrollHeight;
                                    });
                                }""")
                                time.sleep(1.5)

                            job_cards = page.locator(
                                ".base-search-card, .job-card-container, [data-occludable-job-id], .jobs-search-results-list__item"
                            ).all()
                            print(
                                f"    Found {len(job_cards)} job cards on page start={start}."
                            )

                            if not job_cards:
                                print(
                                    "    No cards found on this page. Ending pagination for this keyword."
                                )
                                break

                            new_jobs_added = 0
                            for card in job_cards:
                                if len(jobs_per_keyword) >= limit:
                                    break

                                jobs_temp = []
                                _process_scraped_card(
                                    card,
                                    browser,
                                    jobs_temp,
                                    seen_urls,
                                    seen_companies,
                                    already_submitted_urls,
                                    already_submitted_keys,
                                )

                                for job in jobs_temp:
                                    job_key = f"{job['title']} @ {job['company']}"
                                    if job_key not in seen_job_keys:
                                        seen_job_keys.add(job_key)
                                        jobs_per_keyword.append(job)
                                        all_jobs.append(job)
                                        new_jobs_added += 1

                            print(
                                f"    Added {new_jobs_added} unique jobs from page start={start}."
                            )
                            if new_jobs_added > 0:
                                for idx, job in enumerate(all_jobs):
                                    job["id"] = f"job_{idx}"
                                jobs_file = dirs["jobs_file"]
                                with open(jobs_file, "w", encoding="utf-8") as f:
                                    json.dump(all_jobs, f, indent=2, ensure_ascii=False)
                                print(
                                    f"    [PROGRESSIVE SAVE] Saved {len(all_jobs)} jobs to {jobs_file}"
                                )
                            if new_jobs_added == 0:
                                consecutive_no_new_pages += 1
                                print(
                                    f"    No new unique jobs found on this page (consecutive empty: {consecutive_no_new_pages})."
                                )
                                if consecutive_no_new_pages >= 3:
                                    print(
                                        "    Reached 3 consecutive pages with 0 new unique jobs. Ending pagination loop."
                                    )
                                    break
                            else:
                                consecutive_no_new_pages = 0

                        except Exception as e:
                            print(
                                f"    [WARNING] Failed to scrape page start={start}: {e}"
                            )
                            break

                browser.close()
                browser = None
            except Exception as e:
                err_msg = str(e).lower()
                if (
                    "pipe" in err_msg
                    or "closed" in err_msg
                    or "epipe" in err_msg
                    or isinstance(e, (BrokenPipeError, OSError, EOFError))
                ):
                    print(
                        f"  [CRITICAL] Playwright connection/pipe error: {e}. "
                        f"Saving {len(all_jobs)} partially-scraped jobs and force-exiting to prevent zombie.",
                        flush=True,
                    )
                    try:
                        for idx, job in enumerate(all_jobs):
                            job["id"] = f"job_{idx}"
                        with open(jobs_file, "w", encoding="utf-8") as f:
                            json.dump(all_jobs, f, indent=2, ensure_ascii=False)
                    except:
                        pass
                    import os

                    os._exit(1)
                raise

    except (BrokenPipeError, OSError, EOFError) as epipe_err:
        # Node.js/Playwright pipe broke mid-scrape — log and return partial results.
        # With MultipleInstances=StopExisting this process will exit cleanly; no hang.
        print(
            f"  [CRITICAL] Playwright Node pipe broken: {epipe_err}. "
            f"Returning {len(all_jobs)} partially-scraped jobs.",
            flush=True,
        )
    except Exception as pw_err:
        print(f"  [ERROR] Playwright session failed unexpectedly: {pw_err}", flush=True)
        raise
    finally:
        # Guarantee browser cleanup even if Node driver dies before context.close()
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass

    # Re-index all unique jobs sequentially
    for idx, job in enumerate(all_jobs):
        job["id"] = f"job_{idx}"

    # Save final results
    jobs_file = dirs["jobs_file"]
    with open(jobs_file, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, indent=2, ensure_ascii=False)

    print(
        f"\n[Phase 1: Search] Completed multi-keyword scraping. Found {len(all_jobs)} total unique jobs. Saved to {jobs_file}\n"
    )
    return jobs_file
