"""
core/channel_tracker.py — Channel-Level Ground-Truth Application Tracker & Verification.

Scrapes and parses the candidate's actual applied jobs dashboards across sourcing channels:
1. LinkedIn Job Tracker: https://www.linkedin.com/jobs-tracker/?stage=applied
2. ITViec Applied Dashboard: https://itviec.com/applied_jobs
3. TopCV Applied History: https://www.topcv.vn/lich-su-ung-tuyen

Serves as the authoritative Single Source of Truth (SSOT) to eliminate false positives.
"""

import logging
import re
import time
from typing import Any

from shared_platform.logging_setup import checkpointed_function

logger = logging.getLogger("channel_tracker")


@checkpointed_function(
    function_id="FL-530", use_case_id="UC-003", node_name="channel_tracker"
)
def scrape_linkedin_applied_tracker(page) -> list[dict[str, Any]]:
    """
    Navigates to LinkedIn's Applied Job Tracker and extracts all genuinely applied jobs.
    URL: https://www.linkedin.com/jobs-tracker/?stage=applied
    """
    applied_jobs = []
    tracker_url = "https://www.linkedin.com/jobs-tracker/?stage=applied"

    try:
        logger.info("Navigating to LinkedIn Applied Jobs Tracker: %s", tracker_url)
        page.goto(tracker_url, wait_until="domcontentloaded", timeout=25000)
        time.sleep(3)

        # Scroll to load items
        for _ in range(3):
            page.mouse.wheel(0, 1000)
            time.sleep(1)

        # Candidate item cards on jobs tracker
        card_selectors = [
            ".jobs-tracker-card",
            "li.jobs-tracker-item",
            "div.artdeco-entity-lockup",
            "li[data-occludable-job-id]",
            "div.job-card-container",
        ]

        found_cards = None
        for sel in card_selectors:
            loc = page.locator(sel)
            if loc.count() > 0:
                found_cards = loc
                break

        if not found_cards or found_cards.count() == 0:
            # Fallback: parse entire page body text / list elements
            items = page.locator("div.artdeco-list__item, li.artdeco-list__item")
            if items.count() > 0:
                found_cards = items

        if found_cards:
            total = found_cards.count()
            logger.info("Found %d application cards on LinkedIn tracker.", total)
            for i in range(total):
                try:
                    card = found_cards.nth(i)
                    card_text = card.inner_text().strip()
                    if not card_text:
                        continue

                    # Extract title, company, location, applied_time
                    lines = [ln.strip() for ln in card_text.splitlines() if ln.strip()]
                    title = lines[0] if len(lines) > 0 else "Unknown Title"
                    company = lines[1] if len(lines) > 1 else "Unknown Company"
                    location = lines[2] if len(lines) > 2 else ""

                    applied_relative = ""
                    for line in lines:
                        if re.search(r"\bApplied\s+", line, re.IGNORECASE):
                            applied_relative = line
                            break

                    # Extract job link or ID if available
                    job_url = ""
                    link_el = card.locator("a[href*='/jobs/view/']").first
                    if link_el.count() > 0:
                        href = link_el.get_attribute("href") or ""
                        job_url = href.split("?")[0]

                    applied_jobs.append(
                        {
                            "source": "linkedin",
                            "title": title,
                            "company": company,
                            "location": location,
                            "applied_relative": applied_relative,
                            "url": job_url,
                            "raw_snippet": card_text[:200],
                        }
                    )
                except Exception as card_err:
                    logger.debug("Failed parsing card %d: %s", i, card_err)

        logger.info(
            "Extracted %d applied jobs from LinkedIn tracker.", len(applied_jobs)
        )
    except Exception as e:
        logger.error("Error scraping LinkedIn applied tracker: %s", e)

    return applied_jobs


@checkpointed_function(
    function_id="FL-531", use_case_id="UC-003", node_name="channel_tracker"
)
def scrape_itviec_applied_tracker(page) -> list[dict[str, Any]]:
    """
    Navigates to ITViec's candidate application dashboard and extracts applied jobs.
    URL: https://itviec.com/applied_jobs
    """
    applied_jobs = []
    tracker_url = "https://itviec.com/applied_jobs"

    try:
        logger.info("Navigating to ITViec Applied Jobs Tracker: %s", tracker_url)
        page.goto(tracker_url, wait_until="domcontentloaded", timeout=25000)
        time.sleep(3)

        cards = page.locator(
            ".applied-job-card, .job-item, tr.applied-job-row, div.application-item"
        )
        if cards.count() == 0:
            # Check table rows
            cards = page.locator("table tbody tr")

        total = cards.count()
        logger.info("Found %d application rows on ITViec tracker.", total)
        for i in range(total):
            try:
                card = cards.nth(i)
                text = card.inner_text().strip()
                if not text or "không có hồ sơ" in text.lower():
                    continue

                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                title = lines[0] if len(lines) > 0 else ""
                company = lines[1] if len(lines) > 1 else ""

                applied_jobs.append(
                    {
                        "source": "itviec",
                        "title": title,
                        "company": company,
                        "raw_snippet": text[:200],
                    }
                )
            except Exception as card_err:
                logger.debug("Failed parsing ITViec row %d: %s", i, card_err)

    except Exception as e:
        logger.error("Error scraping ITViec applied tracker: %s", e)

    return applied_jobs


@checkpointed_function(
    function_id="FL-532", use_case_id="UC-003", node_name="channel_tracker"
)
def scrape_topcv_applied_tracker(page) -> list[dict[str, Any]]:
    """
    Navigates to TopCV's application history and extracts applied jobs.
    URL: https://www.topcv.vn/lich-su-ung-tuyen
    """
    applied_jobs = []
    tracker_url = "https://www.topcv.vn/lich-su-ung-tuyen"

    try:
        logger.info("Navigating to TopCV Applied History: %s", tracker_url)
        page.goto(tracker_url, wait_until="domcontentloaded", timeout=25000)
        time.sleep(3)

        cards = page.locator(
            ".box-apply, .history-item, .job-applied-item, tr.job-item"
        )
        total = cards.count()
        logger.info("Found %d application records on TopCV history.", total)
        for i in range(total):
            try:
                card = cards.nth(i)
                text = card.inner_text().strip()
                if not text or "chưa ứng tuyển" in text.lower():
                    continue

                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                title = lines[0] if len(lines) > 0 else ""
                company = lines[1] if len(lines) > 1 else ""

                applied_jobs.append(
                    {
                        "source": "topcv",
                        "title": title,
                        "company": company,
                        "raw_snippet": text[:200],
                    }
                )
            except Exception as card_err:
                logger.debug("Failed parsing TopCV card %d: %s", i, card_err)

    except Exception as e:
        logger.error("Error scraping TopCV applied tracker: %s", e)

    return applied_jobs


def is_job_verified_by_channel_tracker(
    job: dict[str, Any], channel_applied_list: list[dict[str, Any]]
) -> tuple[bool, str]:
    """
    Cross-references a candidate job against the platform's ground-truth applied tracker list.
    Uses normalized company and title token matching.
    """
    job_company = re.sub(r"[^\w\s]", "", (job.get("company") or "").lower()).strip()
    job_title = re.sub(r"[^\w\s]", "", (job.get("title") or "").lower()).strip()
    job_url = (job.get("url") or "").split("?")[0].strip().lower()

    for item in channel_applied_list:
        item_url = (item.get("url") or "").split("?")[0].strip().lower()
        if (
            job_url
            and item_url
            and (job_url == item_url or job_url in item_url or item_url in job_url)
        ):
            return True, f"Matched via URL: {item_url}"

        item_company = re.sub(
            r"[^\w\s]", "", (item.get("company") or "").lower()
        ).strip()
        item_title = re.sub(r"[^\w\s]", "", (item.get("title") or "").lower()).strip()

        # Company matching: either one contains the other or primary tokens match
        company_match = (
            job_company in item_company
            or item_company in job_company
            or any(t in item_company for t in job_company.split() if len(t) > 3)
        )

        # Title matching: key keywords match
        title_tokens_job = set(w for w in job_title.split() if len(w) > 3)
        title_tokens_item = set(w for w in item_title.split() if len(w) > 3)
        title_overlap = len(title_tokens_job.intersection(title_tokens_item))

        if company_match and (
            title_overlap >= 2 or job_title in item_title or item_title in job_title
        ):
            return (
                True,
                f"Matched via Company ('{item.get('company')}') & Title ('{item.get('title')}')",
            )

    return False, "Not found in channel tracker ground truth"
