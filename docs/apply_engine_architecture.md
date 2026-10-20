# JobHunterKit: Apply Engine Architecture

This document outlines the architecture, pipeline, and specific strategies of the automated application engine in JobHunterKit, based on the implementation found in `core/apply_mechanics.py`, `services/applying.py`, and `scripts/flow_apply.py`.

## Architecture Overview
The apply engine operates as a hybrid automation system combining programmatic Playwright commands for speed and a visual LLM-based agent (using Gemini via IPC) for complex, dynamic forms. It uses a queue-based state machine (`status_apply` in the database) with concurrent daemon workers that lock and process jobs using `SELECT FOR UPDATE SKIP LOCKED`.

## Action Vocabulary
The visual parsing agent uses a fixed, strict JSON vocabulary to interact with pages. 
*   **`type`**: Types text into an input field. Target element is located via CSS/Text selector, cleared, and typed out character-by-character with randomized human-like delays.
*   **`click`**: Clicks a button, link, or label. Incorporates a small hover-delay. If a click is intercepted by an overlay, it retries with `force=True`.
*   **`upload`**: Uploads a file (CV) to a specific file input element or locator.
*   **`done`**: Indicates that the application has been successfully submitted and a confirmation page/message is visible. 
*   **`fail`**: Indicates the agent is completely stuck or unable to proceed. Used as a last resort to trigger a fallback to manual intervention.

## Visual Prompt Parsing Pipeline
When an application encounters a dynamic form or an external ATS, it falls back to the agentic visual loop (`_agentic_external_apply`):

1.  **Screenshot Capture**: The page is screenshotted (JPEG, quality=80) and converted to base64.
2.  **DOM Extraction**: A JavaScript evaluator runs in the browser to extract all interactive elements (`input`, `button`, `select`, `textarea`, `a`, `[role="combobox"]`, etc.). It captures their bounding box, `aria-label`, text, placeholder, and disabled/checked states, returning a JSON array of interactive elements. Non-interactive or zero-dimension elements are filtered out.
3.  **Gemini Reasoning**: A prompt is constructed containing the current URL, applicant profile (JSON), CV text snippet, candidate credentials (for account creation), the interactive DOM JSON, and the base64 screenshot.
4.  **Action Execution**: The LLM response is processed via `parse_llm_visual_action`. The parser is highly resilient, attempting:
    *   Standard JSON parsing and trailing-comma repair.
    *   Conversational confirmation detection (e.g., "application successfully submitted").
    *   Markdown key-value regex extraction for `action`, `selector`, `value`, and `reasoning`.
    Once parsed, Playwright executes the action.

## Form Field Detection and Filling Strategy
For known programmatic modals (like LinkedIn Easy Apply), the system uses `_fill_text_inputs` and `_resolve_field_value`:
1.  **Learned Answers**: Checks `applicant_profile.json` under `learned_answers` for previously saved answers to normalized question text.
2.  **Profile Extraction**: Maps standard keywords (e.g., "salary", "experience", "ux", "phone") to the structured `applicant_profile.json` sections (`personal`, `salary`, `experience_years`, `work_authorization`).
3.  **LLM Resolver Fallback**: If the question is unknown, it queries Gemini directly (`_resolve_via_gemini`) with the CV text and question to generate a precise answer (e.g., just the integer "5" for years of experience).
4.  **Interactive / Telegram Loop**: If the LLM is unsure, it prompts the user interactively (if TTY) or via Telegram. The final answer is saved back to `learned_answers` for future use.

## File Upload Handling
The engine supports multiple strategies to upload CVs:
1.  **Direct Input**: Attempts to use `set_input_files` directly on visible `<input type="file">` elements.
2.  **Fallback Chooser**: If direct input fails, it searches for upload labels/buttons (e.g., "Upload resume", "Tải CV lên", `.jobs-document-upload__upload-button`). It clicks these elements and intercepts the Playwright file chooser (`expect_file_chooser`) to attach the tailored CV PDF.

## Retry Logic and Error Recovery
*   **CAPTCHA Handling**: Detects CAPTCHAs (hCaptcha, Turnstile, GeeTest) by scanning DOM attributes and iframe URLs. Uses an external `CaptchaSolver` API to inject tokens. If it fails, it retries once before demoting the job to manual intervention.
*   **LLM Parsing Failures**: If the LLM returns an invalid action or syntax error, the agent retries. After 5 consecutive invalid responses, a **self-healing fallback** attempts to find and blindly click any "Submit" or "Apply" button before completely failing.
*   **Action Execution Failures**: If Playwright fails to execute an action (e.g., element hidden), it retries. 2 consecutive action execution failures abort the loop.
*   **Submission Proof Retry**: If the engine believes it clicked submit but cannot verify the confirmation text/screenshot, it retries the submit click once after a brief delay.
*   **Watchdog Timeout**: Jobs are wrapped in a daemon thread with a hard 600-second timeout. If exceeded, the database is safely reset to `failed_manual` to prevent blocking the worker pool indefinitely.

## Stealth and Anti-Detection Measures
*   **Playwright Stealth**: Uses `playwright_stealth` to mask automation markers.
*   **Browser Fingerprinting**: Hardcodes a generic Windows Chrome User-Agent, masks the timezone (`Asia/Ho_Chi_Minh`), sets a standard viewport, and disables `AutomationControlled` blink features.
*   **Humanized Interactions**: Inputs are typed with random inter-keystroke delays (40-120ms) and preceded by a brief random pause (150-400ms). Clicks incorporate hover-delays.
*   **Cookie/Consent Bypass**: Injects JavaScript to forcefully remove known cookie consent banners (e.g., OneTrust) and re-enable pointer events, preventing modals from intercepting clicks.

## IPC Daemon Integration
LLM calls are offloaded via an IPC bridge (`call_antigravity` in `scripts.ipc_utils`). This isolates the heavy LLM API interactions and manages token limits centrally. For visual tasks, the base64 screenshot is passed alongside the text prompt in a JSON-mode request to guarantee structured outputs.
