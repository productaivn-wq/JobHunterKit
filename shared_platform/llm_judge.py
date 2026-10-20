"""
LLM-as-a-Judge Post-Submission Review & Proof Verification Module for JobHunterKit.

Evaluates job application submission proof screenshots, DOM text, and metadata
to determine whether an application was genuinely submitted successfully, staged,
or requires manual intervention.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Ensure workspace root is in python path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared_platform.logging_setup import log_event
from shared_platform.telemetry import score_trace


from pydantic import BaseModel, Field
from typing import Literal, Optional

class SubmissionReviewVerdict(BaseModel):
    is_valid_submission: bool = Field(description="True ONLY if explicit, unambiguous proof of submission confirmation is verified.")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0.")
    detected_status: Literal["applied", "needs_manual_intervention", "dry_run", "staged_unsubmitted", "already_applied", "expired", "failed"] = Field(
        default="needs_manual_intervention",
        description="Classified status of the submission."
    )

    confirmation_id: Optional[str] = Field(default=None, description="Application reference or confirmation number if visible.")
    reasoning: str = Field(description="Detailed explanation of the review verdict.")
    eai_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Evaluation Alignment Index score (>=0.98 for pass).")


def get_prompt_from_ssot(name: str = "JobHunterKit:application_proof_judge", version: int = 1) -> str:
    """Dynamically retrieves the authoritative prompt template from PromptDBStore (task_manager.prompt_templates)."""
    try:
        from core.db_client import get_connection
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT template_text FROM task_manager.prompt_templates WHERE name = %s AND version = %s AND is_active = 1",
                (name, version),
            )
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
    except Exception as e:
        log_event("warning", f"Prompt SSOT lookup failed for '{name}': {e}. Using fallback.")

    return """You are an expert AI Quality Gate Reviewer evaluating an automated job application submission proof screenshot and telemetry for a candidate.

Target Job Information:
- Job ID: {job_id}
- Company: {company}
- Title: {title}
- Source Portal: {source}
- Job URL: {url}

Proof File Details & Telemetry:
- File Path: {proof_path}
- Extracted Information & OCR Content:
{ocr_text}
- DOM Context Snippet:
{dom_text}

Evaluation Directives & Strict Gatekeeping Rules:
1. GENUINE SUBMISSION PROOF ('applied'):
   - MUST display clear, unambiguous submission confirmation evidence.
   - Examples: "Application Submitted", "Your application was sent to", "Thank you for applying", "Application Received", "We received your application", "Applied on <date>", "Đã ứng tuyển thành công", "Ứng tuyển thành công", "Nộp hồ sơ thành công", "Hồ sơ của bạn đã được gửi", or green confirmed application status badges with confirmation IDs.
2. FALSE POSITIVES & REJECTION CRITERIA ('needs_manual_intervention' or 'failed'):
   - REJECT if the screenshot shows a job posting/card (e.g. Jobright/LinkedIn/Indeed job description card with "Apply Now" / "Apply on Employer Site" buttons).
   - REJECT if the status says "Not Submitted" (e.g. Workday/Candidate Home showing status "Not Submitted" or "Draft").
   - REJECT if application form inputs, screening questions, 'Next'/'Submit' buttons, or step progress bars (e.g. Step 1 of 5) are still visible and unfilled.
   - REJECT if captcha blocks, login walls, or session errors are shown.
   - REJECT if job indicates 'already applied' previously ('already_applied') or job is closed/expired ('expired').
3. DRY-RUN EXECUTION ('dry_run'):
   - Explicitly staged application pages verified before final submission in dry-run mode.

Output a structured evaluation verdict strictly adhering to the JSON schema:
{{
    "is_valid_submission": boolean,
    "confidence": float,
    "detected_status": "applied" | "needs_manual_intervention" | "dry_run" | "already_applied" | "expired" | "failed",
    "confirmation_id": string or null,
    "reasoning": string,
    "eai_score": float
}}
"""


class LLMSubmissionJudge:
    """
    LLM-as-a-Judge reviewer evaluating job application submission proofs.
    """

    def __init__(self, trace_id: str | None = None):
        self.trace_id = trace_id

    def _extract_image_text_fallback(self, image_path: str) -> str:
        """Extract text from proof image using OCR if available, else return basic metadata."""
        if not os.path.exists(image_path):
            return "File does not exist."

        text_snippets = []
        filename = os.path.basename(image_path)
        file_size = os.path.getsize(image_path)
        text_snippets.append(f"Filename: {filename}")
        text_snippets.append(f"File Size: {file_size} bytes")

        # Try pytesseract if installed for OCR
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)
            ocr_text = pytesseract.image_to_string(img)
            if ocr_text and ocr_text.strip():
                text_snippets.append(f"OCR Extracted Text:\n{ocr_text.strip()}")
        except Exception:
            pass  # OCR non-essential

        return "\n".join(text_snippets)

    def evaluate_proof(
        self,
        job_dict: dict[str, Any],
        proof_path: str | None = None,
        dom_text: str | None = None,
    ) -> dict[str, Any]:
        """
        Evaluates application proof artifact via LLM-as-a-Judge and Prompt SSOT.
        """
        job_id = job_dict.get("id", "unknown")
        company = job_dict.get("company", "Unknown Company")
        title = job_dict.get("title", "Unknown Title")
        source = job_dict.get("source", "unknown")
        url = job_dict.get("url", "")

        # Failsafe check 1: Missing proof path
        if not proof_path or not os.path.exists(proof_path):
            log_event(
                "warning",
                f"LLM Judge: Missing proof file for Job #{job_id} ({company})",
                job_id=job_id,
            )
            return {
                "is_valid_submission": False,
                "confidence": 1.0,
                "detected_status": "needs_manual_intervention",
                "confirmation_id": None,
                "reasoning": "No proof file found on disk. Unverified application.",
                "eai_score": 0.0,
                "judge_mode": "pre_check",
            }

        # Failsafe check 2: File size < 500 bytes (empty/corrupted image)
        file_size = os.path.getsize(proof_path)
        if file_size < 500:
            log_event(
                "warning",
                f"LLM Judge: Corrupted proof file ({file_size} bytes) for Job #{job_id}",
                job_id=job_id,
            )
            return {
                "is_valid_submission": False,
                "confidence": 1.0,
                "detected_status": "needs_manual_intervention",
                "confirmation_id": None,
                "reasoning": f"Proof screenshot file is empty or corrupted ({file_size} bytes).",
                "eai_score": 0.0,
                "judge_mode": "pre_check",
            }

        # Failsafe check 3: Hard invalid filename prefixes & status shortcuts
        filename = os.path.basename(proof_path).lower()

        # Check for already applied (NOT a new submission)
        if filename.startswith("already_applied_") or "already_applied" in filename:
            return {
                "is_valid_submission": False,
                "confidence": 1.0,
                "detected_status": "already_applied",
                "confirmation_id": None,
                "reasoning": "Job board indicates candidate already applied for this position in a prior session. Not a new automated submission.",
                "eai_score": 0.0,
                "judge_mode": "pre_check",
            }

        # Check for expired / closed jobs
        expired_prefixes = (
            "closed_",
            "expired_",
            "unavailable_",
            "job_closed_",
        )
        if any(filename.startswith(p) for p in expired_prefixes):
            return {
                "is_valid_submission": False,
                "confidence": 1.0,
                "detected_status": "expired",
                "confirmation_id": None,
                "reasoning": "Job posting is closed, expired, or no longer accepting applications.",
                "eai_score": 0.0,
                "judge_mode": "pre_check",
            }

        invalid_prefixes = (
            "external_captcha_",
            "external_timeout_",
            "external_action_exec_failed_",
            "external_llm_action_failed_",
            "external_stuck_",
            "external_failed_",
            "external_error_",
            "no_modal_",
            "bug_no_apply_",
            "unsubmitted_",
            "portal_page_",
            "proof_failed_",
            "proof_unverified_",
            "stuck_",
            "unrecognized_",
            "unsupported_",
            "staged_",
            "form_page_",
            "manual_submitted_",
            "external_dryrun_",
            "dryrun_",
        )
        if any(filename.startswith(prefix) for prefix in invalid_prefixes):
            matched_prefix = next(p for p in invalid_prefixes if filename.startswith(p))
            is_dryrun_prefix = matched_prefix in ("external_dryrun_", "dryrun_", "staged_")
            return {
                "is_valid_submission": False,
                "confidence": 0.95,
                "detected_status": "staged_unsubmitted" if is_dryrun_prefix else "needs_manual_intervention",
                "confirmation_id": None,
                "reasoning": f"Proof screenshot has explicit failure/unverified prefix '{matched_prefix}'. Strictly lacks post-submission confirmation.",
                "eai_score": 0.0,
                "judge_mode": "pre_check",
            }



        # Extract image details/text for LLM Judge
        extracted_info = self._extract_image_text_fallback(proof_path)

        # Retrieve prompt from Prompt SSOT
        template_str = get_prompt_from_ssot()
        prompt = template_str.format(
            job_id=job_id,
            company=company,
            title=title,
            source=source,
            url=url,
            proof_path=proof_path,
            ocr_text=extracted_info,
            dom_text=dom_text or "None",
        )

        try:
            import base64

            with open(proof_path, "rb") as f:
                b64_image = base64.b64encode(f.read()).decode("utf-8")
            from shared_platform.llm_client import GeminiClient

            client = GeminiClient()
            response_str = client.call(
                prompt, json_mode=True, temperature=0.0, image_b64=b64_image
            )

            # Robust JSON extraction
            cleaned_str = response_str.strip()
            # Extract outermost JSON object if surrounded by markdown or extra text
            match = re.search(r"(\{[\s\S]*\})", cleaned_str)
            if match:
                raw_json = match.group(1)
            else:
                raw_json = cleaned_str

            try:
                res = json.loads(raw_json)
            except json.JSONDecodeError:
                # Handle possible trailing commas or extra data
                res = json.loads(raw_json.split("\n\n")[0]) if "\n\n" in raw_json else {}

            # Field normalization
            is_valid = bool(res.get("is_valid_submission") or res.get("is_valid") or res.get("valid", False))
            confidence = float(res.get("confidence", 0.9))
            detected_status = str(res.get("detected_status") or res.get("status") or ("applied" if is_valid else "needs_manual_intervention"))
            if detected_status not in ("applied", "needs_manual_intervention", "dry_run", "staged_unsubmitted", "already_applied", "expired", "failed"):
                detected_status = "applied" if is_valid else "needs_manual_intervention"
            reasoning = str(res.get("reasoning") or res.get("justification") or res.get("explanation") or "Evaluated by LLM Judge")
            confirmation_id = res.get("confirmation_id") or res.get("application_id")
            eai_score = float(res.get("eai_score", 0.99 if is_valid else 0.0))

            # Validate via Pydantic model
            verdict = SubmissionReviewVerdict(
                is_valid_submission=is_valid,
                confidence=confidence,
                detected_status=detected_status,
                confirmation_id=confirmation_id,
                reasoning=reasoning,
                eai_score=eai_score,
            )
            
            is_valid = verdict.is_valid_submission
            confidence = verdict.confidence
            detected_status = verdict.detected_status
            reasoning = verdict.reasoning
            confirmation_id = verdict.confirmation_id
            eai_score = verdict.eai_score

            if confidence < 0.70 or eai_score < 0.98:
                if is_valid and eai_score < 0.98:
                    is_valid = False
                    detected_status = "needs_manual_intervention"
                    reasoning += f" (EAI score {eai_score:.2f} < 0.98 QualityGate threshold)"

            log_event(
                "info",
                f"LLM Judge verdict for Job #{job_id}: status={detected_status}, valid={is_valid}, conf={confidence:.2f}, EAI={eai_score:.2f}",
                job_id=job_id,
                reasoning=reasoning,
            )

            if self.trace_id:
                score_trace(
                    self.trace_id,
                    "llm_judge_score",
                    eai_score,
                    comment=f"EAI={eai_score:.2f}, Conf={confidence:.2f}: {reasoning}",
                )

            return {
                "is_valid_submission": is_valid,
                "confidence": confidence,
                "detected_status": detected_status,
                "confirmation_id": confirmation_id,
                "reasoning": reasoning,
                "eai_score": eai_score,
                "judge_mode": "llm_judge_prompt_ssot",
            }

        except Exception as err:
            log_event(
                "warning",
                f"LLM Judge evaluation error for Job #{job_id}: {err}. Performing rigorous fallback analysis.",
                job_id=job_id,
            )
            # Rigorous Heuristic Fallback: Do NOT trust filename alone.
            # Require explicit text or OCR matching multi-word confirmation signatures.
            text_to_check = (extracted_info + " " + (dom_text or "")).lower()
            strict_confirmations = [
                "your application was sent",
                "application submitted",
                "application has been submitted",
                "application was submitted",
                "thank you for applying",
                "application received",
                "we received your application",
                "nộp đơn thành công",
                "nộp hồ sơ thành công",
                "gửi cv thành công",
                "gửi hồ sơ thành công",
                "ứng tuyển thành công",
                "chúc mừng bạn đã ứng tuyển thành công",
                "nhà tuyển dụng sẽ liên hệ",
                "hồ sơ đã được gửi thành công",
                "đã nộp đơn",
                "đã ứng tuyển",
                "đã nộp hồ sơ",
                "đã gửi hồ sơ",
                "đã gửi cv",
            ]
            has_strict_text = any(
                phrase in text_to_check for phrase in strict_confirmations
            )

            if has_strict_text:
                return {
                    "is_valid_submission": True,
                    "confidence": 0.85,
                    "detected_status": "applied",
                    "confirmation_id": None,
                    "reasoning": f"Strict text confirmation verified in proof text/OCR. (LLM call failed: {err})",
                    "judge_mode": "strict_text_fallback",
                }
            else:
                return {
                    "is_valid_submission": False,
                    "confidence": 0.90,
                    "detected_status": "needs_manual_intervention",
                    "confirmation_id": None,
                    "reasoning": f"Proof lacks confirmed submission signature in OCR/text. Rejection prevents false positives. (LLM call failed: {err})",
                    "judge_mode": "unverified_safe_fallback",
                }


def evaluate_application_proof(
    job_dict: dict[str, Any],
    proof_path: str | None = None,
    dom_text: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Convenience function for LLM proof evaluation."""
    judge = LLMSubmissionJudge(trace_id=trace_id)
    return judge.evaluate_proof(job_dict, proof_path=proof_path, dom_text=dom_text)
