# JobHunterKit: ATS Portal Matrix

This document outlines the known ATS (Applicant Tracking System) portals, job boards, and their specific handling logic within the JobHunterKit application engine.

## General Fallback Strategy
If a portal is not explicitly hardcoded with programmatic overrides, the engine relies on the **Agentic Visual Flow** (`_agentic_external_apply`). This flow parses the DOM, handles unknown fields via LLM reasoning, and navigates standard multi-page forms autonomously.

## ATS Matrix

| Portal / ATS | Form Structure Type | Supported Mode | Known Quirks & Workarounds | Success Indicators |
| :--- | :--- | :--- | :--- | :--- |
| **LinkedIn (Easy Apply)** | Native Modal | Programmatic | Evaluates nested DOM/iframes for `.jobs-easy-apply-modal`. Handles "Share your profile?" and safety warning overlays. Auto-detects previously applied badges (`.jobs-s-apply--applied`). | "Application submitted", "Thank you for applying", or verified screenshot of completion modal. |
| **VietnamWorks** | External Page / Modal | Programmatic & Agentic | **3-CV Limit Bypass**: Injects JS to click hidden radio buttons and the "Replace" (Thay thế) button programmatically if the candidate has reached their CV limit. | "Nộp đơn thành công", "Successfully submitted" |
| **Workday** | External Page | Agentic | **Email OTP Requirement**: Frequently prompts for verification codes. Engine intercepts this, polls Gmail via `gmail_otp_reader`, extracts the code, and auto-fills the verification input. | "Application received", "Congratulations", "View your application" |
| **Greenhouse** | External Page | Agentic | Custom dropdowns use `react-select`. Engine specifically detects `role="combobox"` and simulates `Focus -> Type -> Enter` instead of standard `fill()`. | Standard submission keywords. |
| **TopCV** | Inline Modal / External | Agentic | Uses inline login modals (`.modal-login`). Detected and auto-filled with credentials from `.env` prior to attempting submission. | "Ứng tuyển thành công", "Đã nộp đơn" |
| **ITViec** | Inline Modal / External | Agentic | Similar to TopCV, handles inline login modals. Handled natively via the `LOGIN_MODAL_SELECTORS` bypass. | Standard submission keywords. |
| **Indeed** | Inline Modal / External | Agentic | Handled via generic modal bypass and agentic flow. | Standard submission keywords. |
| **Careerjet** | External Page | Agentic | Handled entirely by the generic visual agent. Navigates directly to extracted URL. | Standard submission keywords. |
| **Meta Careers** | External Page | Agentic | Handled by generic visual agent. No explicit hardcoded bypass logic. | Handled via generic visual success check. |
| **Augintel** | External Page | Agentic | Handled by generic visual agent. No explicit hardcoded bypass logic. | Handled via generic visual success check. |
| **Coursera** | External Page | Agentic | Handled by generic visual agent. No explicit hardcoded bypass logic. | Handled via generic visual success check. |
| **SAP** | External Page | Agentic | Handled by generic visual agent. No explicit hardcoded bypass logic. | Handled via generic visual success check. |

## General Success Indicators
The engine considers an application successfully submitted if the post-submission page body contains any of the following (case-insensitive):
*   "application submitted"
*   "thank you for applying"
*   "application received"
*   "your application was sent"
*   "successfully submitted"
*   "nộp đơn thành công"
*   "cảm ơn bạn đã nộp đơn"
*   "ứng tuyển thành công"
*   "your candidate profile has been created"
*   "submission received"

If explicit text isn't found, the engine attempts a secondary **LLM Visual Proof Verification**, asking Gemini to review the screenshot and return JSON confirming if it visually represents a successful submission.

## Known Limitations and Unsupported Form Types
1.  **Unsolvable CAPTCHAs**: While hCaptcha, Turnstile, and GeeTest are supported via API, proprietary or heavily obfuscated bot protection (e.g., extreme Cloudflare bot-fight mode blocking headless browsers entirely) will fail and route to manual intervention.
2.  **Complex Multi-Step Account Creation**: If an ATS requires email verification that sends a magic link rather than an OTP code, the agentic flow will get stuck, as it only currently polls for numeric OTPs.
3.  **Mandatory Non-Standard File Uploads**: If an ATS requires a mandatory portfolio upload (separate from CV) and the agent cannot find a matching file, it may loop and eventually fail to manual intervention.
4.  **Cookie Consents in iframes**: While main-page cookie banners are stripped via JS (`#onetrust-consent-sdk`, etc.), aggressive cookie modals deeply nested inside cross-origin iframes may occasionally block element interaction.
