"""
Application submission and status checking mechanics for JobHunterKit.
Implements dry-run verification prioritization and pause-before-submit controls.
"""

import logging
import os
import re
import sys
import time
from pathlib import Path

# Ensure kit root is on sys.path
KIT_ROOT = str(Path(__file__).resolve().parent.parent)
if KIT_ROOT not in sys.path:
    sys.path.insert(0, KIT_ROOT)

from core.file_utils import safe_filename

logger = logging.getLogger(__name__)

# Early detection selectors for status checking
ALREADY_APPLIED_SELECTORS = [
    'button:has-text("Applied")',
    'button:has-text("Đã ứng tuyển")',
    'span:has-text("Applied")',
    'span:has-text("Đã ứng tuyển")',
    'button:has-text("Applied on")',
    'span:has-text("Applied on")',
    'text="Application submitted"',
    'span:has-text("Application submitted")',
    'div:has-text("Application submitted")',
    'p:has-text("Application submitted")',
    'text="You applied"',
    'text="You\'ve applied"',
    'text="Đã nộp đơn"',
    'text="Đã ứng tuyển"',
    'text="Đã nộp hồ sơ"',
    ".jobs-s-apply--applied",
]

CLOSED_SELECTORS = [
    'text="This job is no longer accepting applications"',
    'text="No longer accepting applications"',
    'span:has-text("No longer accepting applications")',
    'text="no longer active"',
    'text="Đã dừng nhận hồ sơ"',
    'text="Không còn nhận hồ sơ"',
    'text="Hết hạn tuyển dụng"',
    'text="Hết hạn nhận hồ sơ"',
    'span:has-text("Expired")',
    'text="Expired"',
    ".jobs-search-page__closed-job-message",
    '.artdeco-inline-feedback--error:has-text("No longer accepting applications")',
    ".jobs-details__top-card .artdeco-inline-feedback--error",
]


def check_already_applied(page, job, dirs) -> bool:
    """Checks early and fallback selectors on the page to see if already applied."""
    is_already_applied = False
    for sel in ALREADY_APPLIED_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and any(
                loc.nth(i).is_visible() for i in range(loc.count())
            ):
                is_already_applied = True
                break
        except Exception as ex:
            logger.debug("Selector %s inspection failed: %s", sel, ex)

    # Check page text for in-page applied badges (e.g. ITViec "Applied DD/MM/YYYY" or LinkedIn "Application submitted")
    if not is_already_applied:
        try:
            text = ""
            if hasattr(page, "locator"):
                loc = page.locator("body")
                try:
                    text = loc.inner_text()
                except Exception as inner_ex:
                    logger.debug("Body inner_text extraction failed: %s", inner_ex)
            if not text and hasattr(page, "content"):
                text = page.content()
            text_lower = text.lower()
            if (
                re.search(r"Applied\s+\d{2}/\d{2}/\d{4}", text, re.IGNORECASE)
                or "đã ứng tuyển" in text_lower
                or "application submitted" in text_lower
                or ("application status" in text_lower and "submitted" in text_lower)
            ):
                is_already_applied = True
        except Exception as ex:
            logger.debug("In-page badge text search failed: %s", ex)

    if is_already_applied:
        print(
            f"  [ALREADY APPLIED] Job is already applied: {job['title']} at {job['company']}"
        )
        job["apply_status"] = "Skipped (Already Applied)"
        proof_dir = dirs.get("proof_dir", "") if isinstance(dirs, dict) else ""
        if proof_dir:
            os.makedirs(proof_dir, exist_ok=True)
            proof_file = os.path.join(
                proof_dir,
                f"already_applied_{safe_filename(job['company'])}__{job['id']}.png",
            )
            try:
                page.screenshot(path=proof_file)
                job["proof_path"] = proof_file
                print(
                    f"  [SCREENSHOT] Captured already applied screenshot: {proof_file}"
                )
            except Exception as se:
                print(f"  [WARNING] Failed to capture already applied screenshot: {se}")
        return True
    return False


def check_job_closed(page, job, dirs) -> bool:
    """Checks early and fallback selectors on the page to see if job is closed."""
    is_closed = False

    # Check page title
    try:
        if hasattr(page, "title"):
            title = page.title
            title_str = title() if callable(title) else str(title)
            if any(
                k in title_str.lower() for k in ["job expired", "expired", "hết hạn"]
            ):
                is_closed = True
    except Exception as ex:
        logger.debug("Title inspection failed: %s", ex)

    if not is_closed:
        for sel in CLOSED_SELECTORS:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and any(
                    loc.nth(i).is_visible() for i in range(loc.count())
                ):
                    is_closed = True
                    break
            except Exception as ex:
                logger.debug("Closed selector %s inspection failed: %s", sel, ex)

    if is_closed:
        print(f"  [CLOSED] Job is no longer active: {job['title']} at {job['company']}")
        job["apply_status"] = "Skipped (Job Closed)"
        proof_dir = dirs.get("proof_dir", "") if isinstance(dirs, dict) else ""
        if proof_dir:
            os.makedirs(proof_dir, exist_ok=True)
            proof_file = os.path.join(
                proof_dir,
                f"closed_{safe_filename(job['company'])}__{job['id']}.png",
            )
            try:
                page.screenshot(path=proof_file)
                job["proof_path"] = proof_file
                print(f"  [SCREENSHOT] Captured closed job screenshot: {proof_file}")
            except Exception as se:
                print(f"  [WARNING] Failed to capture closed job screenshot: {se}")
        return True
    return False


def check_submission_confirmation(url: str, page_content: str) -> bool:
    """Returns True if the URL or page content contains submission success confirmation without errors."""
    url_lower = str(url).lower()
    page_content_lower = str(page_content).lower()

    # Reject if error indicators are present
    error_keywords = [
        "error submitting",
        "field is required",
        "please enter a valid",
        "validation error",
        "something went wrong",
        "failed to submit",
    ]
    if any(err in page_content_lower for err in error_keywords):
        return False

    # Strong confirmation phrases in page text
    success_phrases = [
        "submitted successfully",
        "application has been submitted",
        "application submitted",
        "application received",
        "nộp đơn ứng tuyển thành công",
        "nộp đơn thành công",
        "ứng tuyển thành công",
        "nộp hồ sơ thành công",
        "hồ sơ của bạn đã được gửi",
        "cảm ơn bạn đã nộp đơn",
        "cảm ơn bạn đã ứng tuyển",
        "chúc mừng",
        "đã nộp đơn",
        "đã ứng tuyển",
        "đã gửi hồ sơ",
        "bạn đã ứng tuyển công việc này",
        "thank you for applying",
        "thanks for applying",
        "your application was sent",
        "application sent",
        "applied on",
    ]
    if any(phrase in page_content_lower for phrase in success_phrases):
        return True

    # Strict URL path checks (avoid generic query parameters)
    from urllib.parse import urlparse

    try:
        path = urlparse(url_lower).path
        if any(k in path for k in ["/success", "/thank", "/confirmed", "/submitted"]):
            return True
    except Exception as ex:
        logger.debug("URL path inspection failed: %s", ex)

    return False


def handle_easy_apply_submission(page, submit_btn, job, dirs, dry_run) -> bool:
    """Handles the final submission block for Easy Apply.

    Ensures dry-run verification is prioritized and pause/log before actual submission.
    """
    proof_path = os.path.join(
        dirs["proof_dir"], f"{safe_filename(job['company'])}__{job['id']}.png"
    )
    if dry_run:
        # Prioritize dry-run verification: capture screenshot & set status
        print(
            f"  [DRY RUN] Prioritizing dry-run verification for {job['title']} @ {job['company']}. Bypassing submission click."
        )
        try:
            page.screenshot(path=proof_path)
            job["proof_path"] = proof_path
        except Exception as se:
            print(f"  [WARNING] Failed to capture dry-run screenshot: {se}")
        job["apply_status"] = "Success (Dry Run)"
        print("  [SUCCESS] (Dry Run) Application flow completed!")
        return True
    else:
        # Pause and log before any actual submission to verify equivalent behavior
        print(
            f"  [SUBMIT] WARNING: Pausing for 5 seconds before performing ACTUAL submission for {job['title']} at {job['company']} to verify equivalent behavior..."
        )
        time.sleep(5)
        print("  [SUBMIT] Clicking submit button now.")
        submit_btn.click()
        time.sleep(3)
        try:
            page.screenshot(path=proof_path)
            job["proof_path"] = proof_path
        except Exception as se:
            print(f"  [WARNING] Failed to capture submission screenshot: {se}")
        job["apply_status"] = "Success (Submitted)"
        print("  [SUCCESS] Application submitted successfully!")
        return True


def handle_external_agent_submission_intercept(
    page, selector, job, dirs, dry_run
) -> bool:
    """Checks if the agent click action targets a submit button in dry-run mode.

    If dry-run is enabled and click is a submit button, intercepts it and sets dry-run status.
    """
    if not dry_run:
        return False

    is_submit_click = False
    try:
        target_el = page.locator(selector).first
        if target_el.count() > 0:
            btn_text = target_el.inner_text().strip().lower()
            submit_keywords = [
                "submit",
                "apply",
                "finish",
                "complete",
                "nộp đơn",
                "gửi",
                "ứng tuyển",
            ]
            if any(kw in btn_text for kw in submit_keywords):
                is_submit_click = True
    except Exception as ce:
        print(f"  [AGENT DEBUG] Failed to inspect element text for dry-run check: {ce}")

    if is_submit_click:
        print(f"  [DRY RUN] Intercepted final submission click on selector: {selector}")
        dry_run_proof = os.path.join(
            dirs["proof_dir"],
            f"external_dryrun_{safe_filename(job['company'])}__{job['id']}.png",
        )
        try:
            page.screenshot(path=dry_run_proof)
            job["proof_path"] = dry_run_proof
        except Exception as se:
            print(f"  [WARNING] Failed to capture dry-run screenshot: {se}")
        job["apply_status"] = "Success (Dry Run)"
        return True
    return False


def handle_external_agent_done(page, job, dirs, dry_run) -> None:
    """Handles agentic loop 'done' action, performing screenshot and setting status."""
    print("  [AGENT] Successfully completed application!")
    success_proof = os.path.join(
        dirs["proof_dir"],
        f"external_submitted_{safe_filename(job['company'])}__{job['id']}.png",
    )
    try:
        page.screenshot(path=success_proof)
        job["proof_path"] = success_proof
    except Exception as se:
        print(f"  [WARNING] Failed to capture agent success screenshot: {se}")

    job["apply_status"] = "Success (Dry Run)" if dry_run else "Success (Submitted)"


def monitor_manual_submission(monitor_page, job, dirs, timeout_limit) -> bool:
    """Monitors the browser page for manual submission detection."""
    start_time = time.time()
    while time.time() - start_time < timeout_limit:
        try:
            if monitor_page.is_closed():
                print("  [MANUAL] Page closed.")
                break

            curr_url = monitor_page.url.lower()
            content = monitor_page.content().lower()

            if check_submission_confirmation(curr_url, content):
                print(
                    "  [MANUAL] Detected application submission! Capturing success screenshot..."
                )
                # Pause/log before any actual submission verification/logging
                time.sleep(3)
                success_proof = os.path.join(
                    dirs["proof_dir"],
                    f"manual_submitted_{safe_filename(job['company'])}__{job['id']}.png",
                )
                try:
                    monitor_page.screenshot(path=success_proof)
                    job["proof_path"] = success_proof
                except Exception as se:
                    print(
                        f"  [WARNING] Failed to capture manual success screenshot: {se}"
                    )
                job["apply_status"] = "Success (Submitted)"
                return True
        except Exception as pe:
            print(f"  [MANUAL DEBUG] Exception inside loop: {pe}")
            try:
                if monitor_page.is_closed():
                    print("  [MANUAL] Page closed.")
                    break
            except Exception as ce:
                print(f"  [MANUAL DEBUG] Page is_closed check failed: {ce}")
                break
        time.sleep(2)
    return False
