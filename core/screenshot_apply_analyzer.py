"""
core/screenshot_apply_analyzer.py — Multimodal Screenshot & Application Route Analyzer.

Inspects application screenshots (proof_failed, stuck, diagnostic, external portal)
using Gemini Vision and JD text extraction to:
  1. Detect if the job can be auto-applied or auto-healed.
  2. Detect if already applied or closed/expired.
  3. Extract precise, actionable instructions, recruiter emails, and portal URLs for manual applications.
"""

import base64
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared_platform.logging_setup import checkpointed_function

logger = logging.getLogger("screenshot_apply_analyzer")

# Common regex patterns for emails and application links in JD text
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")
LINK_REGEX = re.compile(
    r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
)

# Email address blacklists (system notifications, image placeholders, etc.)
EMAIL_IGNORE_LIST = {
    "noreply@",
    "no-reply@",
    "donotreply@",
    "support@",
    "privacy@",
    "help@",
    "feedback@",
    "example.com",
    "domain.com",
}


def extract_emails_from_text(text: str) -> list[str]:
    """Extract valid recruiter/application email addresses from text."""
    if not text:
        return []
    found = EMAIL_REGEX.findall(text)
    valid_emails = []
    for email in found:
        e_lower = email.lower()
        if not any(ignore in e_lower for ignore in EMAIL_IGNORE_LIST):
            if e_lower not in valid_emails:
                valid_emails.append(email)
    return valid_emails


def find_job_screenshot(
    job: dict[str, Any], dirs: dict[str, str] | None = None
) -> str | None:
    """
    Finds the most relevant diagnostic or failure screenshot for a given job.
    Searches in job['proof_path'], dirs['proof_dir'], data/campaigns, and scratch.
    """
    # 1. Direct proof_path attribute
    proof_path = job.get("proof_path")
    if proof_path and os.path.exists(proof_path) and os.path.getsize(proof_path) > 0:
        return proof_path

    job_id = str(job.get("id", ""))
    if not job_id:
        return None

    # 2. Check candidate directories
    candidate_dirs = []
    if dirs and dirs.get("proof_dir"):
        candidate_dirs.append(dirs["proof_dir"])

    try:
        from shared_platform.paths import STORAGE_ROOT

        campaigns_dir = Path(STORAGE_ROOT) / "campaigns"
        if campaigns_dir.exists():
            candidate_dirs.append(str(campaigns_dir))
    except Exception:
        pass

    scratch_dir = _project_root / "scratch"
    if scratch_dir.exists():
        candidate_dirs.append(str(scratch_dir))

    # Priority order for screenshot naming conventions
    priority_prefixes = [
        f"proof_failed_{job_id}",
        f"stuck_{job_id}",
        "external_stuck_",
        "external_action_exec_failed_",
        "bug_no_apply_",
        f"diagnostic_view_{job_id}",
        f"diagnostic_full_{job_id}",
        "external_dryrun_",
        f"proof_submitted_{job_id}",
    ]

    for c_dir in candidate_dirs:
        if not os.path.exists(c_dir):
            continue
        p_path = Path(c_dir)
        try:
            # 1. Fast direct glob in candidate directory
            direct_pngs = list(p_path.glob(f"*{job_id}*.png"))
            if not direct_pngs and p_path.name == "campaigns":
                # Only check immediate date subdirectories, not deep recursive tree
                for sub in list(p_path.iterdir())[:5]:
                    if sub.is_dir():
                        direct_pngs.extend(list(sub.glob(f"*{job_id}*.png")))

            if direct_pngs:
                # Rank by priority prefix
                for prefix in priority_prefixes:
                    for png in direct_pngs:
                        if prefix in png.name and png.stat().st_size > 0:
                            return str(png)
                for png in direct_pngs:
                    if png.stat().st_size > 0:
                        return str(png)
        except Exception as scan_err:
            logger.debug(
                "Error scanning directory %s for screenshots: %s", c_dir, scan_err
            )

    return None


@checkpointed_function(
    function_id="FL-520", use_case_id="UC-003", node_name="screenshot_analyzer"
)
def analyze_manual_job_screenshot(
    job: dict[str, Any],
    screenshot_path: str | None = None,
    dirs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Multimodal Vision + Text Analyzer for jobs requiring manual intervention.
    Returns a comprehensive analysis dict with route classification and actionable instructions.
    """
    job_id = job.get("id", "unknown")
    company = job.get("company", "Unknown Company")
    title = job.get("title", "Unknown Title")
    jd_text = job.get("jd_text") or ""
    job_url = job.get("url") or ""

    if not screenshot_path:
        screenshot_path = find_job_screenshot(job, dirs)

    # 1. Text-based heuristic analysis
    emails_in_jd = extract_emails_from_text(jd_text)

    from core.company_extractor import is_jd_text_expired

    is_exp, exp_reason = is_jd_text_expired(jd_text, title)

    analysis_result = {
        "job_id": job_id,
        "company": company,
        "title": title,
        "url": job_url,
        "screenshot_path": screenshot_path,
        "can_auto_apply": False,
        "is_already_applied": False,
        "is_job_closed": is_exp,
        "route_type": "JOB_CLOSED" if is_exp else "MANUAL_APPLY_REQUIRED",
        "actionable_instructions": f"Job posting is closed/expired: {exp_reason}"
        if is_exp
        else f"Open application link ({job_url}) and complete submission manually.",
        "detected_emails": emails_in_jd,
        "detected_url": job_url,
        "confidence": 0.95 if is_exp else 0.5,
    }

    if screenshot_path:
        sc_name = os.path.basename(screenshot_path).lower()
        if sc_name.startswith("closed_") or "closed" in sc_name:
            analysis_result["is_job_closed"] = True
            analysis_result["route_type"] = "JOB_CLOSED"
            analysis_result["actionable_instructions"] = (
                "Job posting is closed/expired (detected via closed screenshot)."
            )
        elif sc_name.startswith("already_applied_") or "already_applied" in sc_name:
            analysis_result["is_already_applied"] = True
            analysis_result["route_type"] = "ALREADY_APPLIED"
            analysis_result["actionable_instructions"] = (
                "Candidate has already applied for this position."
            )

    if emails_in_jd and not analysis_result["is_job_closed"]:
        analysis_result["route_type"] = "DIRECT_EMAIL"
        analysis_result["actionable_instructions"] = (
            f"Send CV directly to {', '.join(emails_in_jd)} with subject "
            f"[{title}] - Candidate."
        )

    # 2. Multimodal Vision Analysis if screenshot exists
    if (
        screenshot_path
        and os.path.exists(screenshot_path)
        and os.path.getsize(screenshot_path) > 0
    ):
        try:
            with open(screenshot_path, "rb") as f:
                img_bytes = f.read()
            b64_image = base64.b64encode(img_bytes).decode("utf-8")

            prompt = f"""You are an elite autonomous recruitment & web automation engineer.
Analyze this job application failure/stuck screenshot for Job: "{title}" at "{company}".
Job URL: {job_url}
Job Description Text Snippet (first 500 chars):
{jd_text[:500]}

Classify the state across 6 Mutually Exclusive, Collectively Exhaustive (MECE) Dimensions:
1. "session_auth": Cookie drop, login wall, overlay modal backdrop, captcha challenge.
2. "job_lifecycle": Already applied badge or job posting closed/expired.
3. "nav_routing": External ATS portal (Workday, Greenhouse, Lever) or direct recruiter email.
4. "data_mechanics": Unfilled form inputs, custom screening questions, missing resume upload.
5. "multistep_otp": Next/Review pagination button waiting or OTP code requested.
6. "verification_proof": Submission confirmed or false-negative rejection.

Return JSON ONLY matching this schema:
{{
  "mece_dimension": "DIM_1_SESSION_AUTH" | "DIM_2_JOB_LIFECYCLE" | "DIM_3_NAV_ROUTING" | "DIM_4_DATA_MECHANICS" | "DIM_5_MULTISTEP_OTP" | "DIM_6_VERIFICATION_PROOF",
  "is_already_applied": boolean,
  "is_job_closed": boolean,
  "can_auto_apply": boolean,
  "auto_apply_selector": string or null,
  "route_type": "DIRECT_EMAIL" | "EXTERNAL_PORTAL_SIGNUP" | "WORKDAY_LOGIN" | "CAPTCHA_MANUAL" | "CUSTOM_SCREENING_QUESTIONS" | "DOCUMENT_UPLOAD" | "ALREADY_APPLIED" | "JOB_CLOSED" | "GENERAL_MANUAL",
  "actionable_instructions": string,
  "detected_emails": [string],
  "detected_apply_url": string or null,
  "confidence": number between 0.0 and 1.0
}}
"""
            try:
                try:
                    from shared_platform.llm_client import GeminiClient
                except ImportError:
                    import sys
                    from pathlib import Path

                    root = Path(__file__).resolve().parent.parent
                    if str(root) not in sys.path:
                        sys.path.insert(0, str(root))
                    from shared_platform.llm_client import GeminiClient
                client = GeminiClient()
                resp = client.call(prompt, json_mode=True, image_b64=b64_image)
            except Exception as llm_err:
                logger.warning(
                    "LLM Vision call failed for screenshot analysis: %s", llm_err
                )
                resp = None

            if resp:
                clean_json = resp.strip()
                if clean_json.startswith("```"):
                    clean_json = re.sub(
                        r"^```(?:json)?\s*|\s*```$", "", clean_json, flags=re.DOTALL
                    )
                parsed = json.loads(clean_json)

                analysis_result["mece_dimension"] = parsed.get(
                    "mece_dimension", "DIM_4_DATA_MECHANICS"
                )
                analysis_result["is_already_applied"] = bool(
                    parsed.get("is_already_applied", False)
                )
                analysis_result["is_job_closed"] = bool(
                    parsed.get("is_job_closed", False)
                )
                analysis_result["can_auto_apply"] = bool(
                    parsed.get("can_auto_apply", False)
                )
                analysis_result["route_type"] = (
                    parsed.get("route_type") or analysis_result["route_type"]
                )

                instructions = parsed.get("actionable_instructions")
                if instructions and len(instructions.strip()) > 5:
                    analysis_result["actionable_instructions"] = instructions.strip()

                vis_emails = parsed.get("detected_emails") or []
                for ve in vis_emails:
                    if ve and ve not in analysis_result["detected_emails"]:
                        analysis_result["detected_emails"].append(ve)

                vis_url = parsed.get("detected_apply_url")
                if vis_url and vis_url.startswith("http"):
                    analysis_result["detected_url"] = vis_url

                analysis_result["confidence"] = float(parsed.get("confidence", 0.85))

        except Exception as vision_err:
            logger.warning(
                "Failed multimodal screenshot analysis for Job %s: %s",
                job_id,
                vision_err,
            )

    return analysis_result


def format_manual_job_digest_entry(
    idx: int, analysis: dict[str, Any], tailored_cv_path: str | None = None
) -> str:
    """Formats a single manual job entry for the 1-hour Telegram digest."""
    import html

    company = html.escape(str(analysis.get("company", "Unknown Company")))
    title = html.escape(str(analysis.get("title", "Unknown Title")))
    url = html.escape(str(analysis.get("url") or analysis.get("detected_url") or ""))
    instructions = html.escape(
        str(analysis.get("actionable_instructions", "Apply manually via link."))
    )
    route = analysis.get("route_type", "MANUAL")
    dimension = analysis.get("mece_dimension", "DIM_4_DATA_MECHANICS")
    emails = analysis.get("detected_emails") or []

    dim_badges = {
        "DIM_1_SESSION_AUTH": "🔐 [Auth/Session]",
        "DIM_2_JOB_LIFECYCLE": "⏳ [Lifecycle/Closed]",
        "DIM_3_NAV_ROUTING": "🌐 [ATS/Routing]",
        "DIM_4_DATA_MECHANICS": "📝 [Form/Fields]",
        "DIM_5_MULTISTEP_OTP": "🔢 [Wizard/OTP]",
        "DIM_6_VERIFICATION_PROOF": "🔍 [Verification]",
    }
    dim_badge = dim_badges.get(dimension, "📌 [Application]")

    # Icon based on route type
    route_icons = {
        "DIRECT_EMAIL": "📧",
        "EXTERNAL_PORTAL_SIGNUP": "🌐",
        "WORKDAY_LOGIN": "🏢",
        "CAPTCHA_MANUAL": "🧩",
        "CUSTOM_SCREENING_QUESTIONS": "📝",
        "DOCUMENT_UPLOAD": "📎",
        "ALREADY_APPLIED": "✅",
        "JOB_CLOSED": "🔒",
        "GENERAL_MANUAL": "👉",
    }
    icon = route_icons.get(route, "👉")

    lines = [
        f"{dim_badge} <b>{idx}. {company} — {title}</b>",
        f"{icon} <b>How to Apply:</b> {instructions}",
    ]

    if emails:
        clean_emails = ", ".join(emails)
        lines.append(
            f"✉️ <b>Recruiter Email:</b> <code>{html.escape(clean_emails)}</code>"
        )

    if tailored_cv_path and os.path.exists(tailored_cv_path):
        cv_name = os.path.basename(tailored_cv_path)
        lines.append(f"📄 <b>Tailored CV:</b> <code>{html.escape(cv_name)}</code>")

    if url:
        lines.append(f'🔗 <a href="{url}">Open Job Posting</a>')

    return "\n".join(lines)
