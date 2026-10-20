import json
import os
import re
import sys
import time
from pathlib import Path


# Setup path for importing shared_platform and core
def _setup_sys_path():
    curr = Path(__file__).resolve()
    for parent in curr.parents:
        if (parent / "shared_platform").is_dir():
            root_path = str(parent)
            if root_path not in sys.path:
                sys.path.insert(0, root_path)
            break


_setup_sys_path()

from core.apply_mechanics import (
    check_already_applied,
    check_job_closed,
    monitor_manual_submission,
    safe_filename,
)
from services.common import (
    PLAYWRIGHT_AVAILABLE,
    _load_applied_history,
    _save_applied_history,
)
from shared_platform.llm_client import GeminiClient

if PLAYWRIGHT_AVAILABLE:
    from playwright.sync_api import sync_playwright

services_dir = os.path.dirname(os.path.abspath(__file__))
kit_dir = os.path.dirname(services_dir)
scripts_dir = os.path.join(kit_dir, "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)


def _resolve_contact_from_profile(q, personal) -> str:
    if any(kw in q for kw in ["phone", "mobile", "contact number", "tel"]):
        return str(personal.get("phone", ""))
    if "email" in q and "address" not in q:
        return str(personal.get("email", ""))
    if "name" in q and ("full" in q or "first" in q or "last" in q):
        return str(personal.get("full_name", ""))
    return ""


def _resolve_social_from_profile(q, personal, work_auth) -> str:
    if any(kw in q for kw in ["city", "location", "address"]):
        return str(personal.get("city", ""))
    if any(
        kw in q for kw in ["linkedin", "profile url", "website", "portfolio", "github"]
    ):
        return str(personal.get("linkedin", ""))
    if any(kw in q for kw in ["notice", "start date", "availability"]):
        return str(work_auth.get("notice_period_days", ""))
    return ""


def _resolve_personal_from_profile(q, personal, work_auth) -> str:
    ans = _resolve_contact_from_profile(q, personal)
    if ans:
        return ans
    return _resolve_social_from_profile(q, personal, work_auth)


def _get_expect_salary(q, salary) -> float:
    is_expect = "expect" in q or "desire" in q
    if "vnd" in q or "vietnam" in q:
        return (
            salary.get("expected_vnd", 0) if is_expect else salary.get("current_vnd", 0)
        )
    if "usd" in q or "$" in q:
        return (
            salary.get("expected_usd", 0) if is_expect else salary.get("current_usd", 0)
        )

    expected_base = salary.get("expected_vnd", salary.get("expected_usd", 0) * 25000)
    current_base = salary.get("current_vnd", salary.get("current_usd", 0) * 25000)
    return expected_base if is_expect else current_base


def _resolve_salary_from_profile(q, salary) -> str:
    if not any(kw in q for kw in ["salary", "compensation", "pay"]):
        return ""
    val = _get_expect_salary(q, salary)
    return str(int(val)) if val else ""


def _resolve_experience_from_profile(q, exp) -> str:
    if not any(kw in q for kw in ["year", "experience", "how long", "how many"]):
        return ""
    domain_keywords = {
        "ux": "ux",
        "user experience": "ux",
        "ui": "ux",
        "product": "product_management",
        "product manage": "product_management",
        "ai": "ai_ml",
        "machine learning": "ai_ml",
        "ml": "ai_ml",
        "artificial intelligence": "ai_ml",
        "data": "data_analysis",
        "analytics": "data_analysis",
        "data analysis": "data_analysis",
        "agile": "agile_scrum",
        "scrum": "agile_scrum",
        "crm": "crm",
        "customer relationship": "crm",
        "saas": "saas",
        "b2b": "saas",
        "software as a service": "saas",
        "leadership": "leadership",
        "lead": "leadership",
        "managing": "leadership",
        "manage team": "leadership",
        "project": "project_management",
        "software": "software_development",
        "develop": "software_development",
        "engineering": "software_development",
        "marketing": "marketing",
        "sales": "sales",
        "devops": "devops",
        "ci/cd": "devops",
        "cloud": "cloud",
        "aws": "cloud",
        "gcp": "cloud",
        "azure": "cloud",
        "no.code": "no_code",
        "no-code": "no_code",
        "low.code": "no_code",
        "prompt": "prompt_engineering",
        "llm": "llm",
        "large language": "llm",
        "generative ai": "llm",
        "genai": "llm",
        "stakeholder": "stakeholder_management",
        "people": "people_management",
        "team management": "people_management",
        "remote": "remote_work",
    }
    for keyword, profile_key in domain_keywords.items():
        if keyword in q:
            val = exp.get(profile_key)
            if val is not None:
                return str(val)
    return ""


def _resolve_from_profile(q, profile) -> str:
    """Helper to resolve common form questions from the profile dictionary."""
    personal = profile.get("personal", {})
    salary = profile.get("salary", {})
    exp = profile.get("experience_years", {})
    work_auth = profile.get("work_authorization", {})

    ans = _resolve_personal_from_profile(q, personal, work_auth)
    if ans:
        return ans
    ans = _resolve_salary_from_profile(q, salary)
    if ans:
        return ans
    return _resolve_experience_from_profile(q, exp)


def _resolve_via_gemini(question_text, profile, cv_text) -> str:
    """Helper to query Gemini API for an answer to a form question using consolidated client."""
    prompt = f"""
You are an applicant filling out a job application form.
Your task is to answer a specific screening question based strictly on your profile and CV text.

APPLICANT PROFILE:
{json.dumps(profile, indent=2)}

APPLICANT CV TEXT:
{cv_text}

SCREENING QUESTION FROM THE FORM:
"{question_text}"

Answer the question directly, concisely, and accurately based on the provided information.
- If it asks for years of experience (e.g. "How many years of UX experience do you have?"), return ONLY the number as a whole integer (e.g., "5"). Do not include any words, symbols, or formatting.
- If it asks for a salary, return the number matching the requested currency.
- If it is a Yes/No question, return exactly "Yes" or "No".
- Keep answers as simple and exact as possible. Return ONLY the answer value itself to be entered directly into the form input field.
"""
    try:
        client = GeminiClient()
        ai_answer = client.call(prompt, json_mode=False, temperature=0.0).strip()
        print(f"  [AI SUGGESTION] Resolved '{question_text}' => '{ai_answer}'")
        return ai_answer
    except Exception as e:
        print(f"  [WARNING] Gemini question resolution failed: {e}")
        return ""


def _save_learned_answer(profile, profile_path, q_norm, final_answer, question_text):
    if profile_path and os.path.exists(profile_path):
        try:
            import threading

            global profile_lock
            if "profile_lock" not in globals():
                profile_lock = threading.Lock()
            with profile_lock:
                profile.setdefault("learned_answers", {})[q_norm] = final_answer
                with open(profile_path, "w", encoding="utf-8") as f:
                    json.dump(profile, f, indent=2, ensure_ascii=False)
            print(f"  [LEARNED SAVED] Saved answer for '{question_text}' to profile.")
        except Exception as e:
            print(f"  [WARNING] Could not save learned answer to profile: {e}")


def _get_interactive_screening_answer(question_text, suggestion) -> str:
    print(
        f'\\n{"─" * 50}\\n  [SCREENING QUESTION REQUIRED] Need answer for:\\n  Question: "{question_text}"'
    )
    user_input = input(f"  Suggested Answer [{suggestion}]: ").strip()
    final_answer = user_input if user_input else suggestion
    print(f"{'─' * 50}\\n")
    return final_answer


def _resolve_field_value(
    question_text: str, profile: dict, cv_text: str = "", profile_path: str = ""
) -> str:
    """Resolves the correct value for a LinkedIn Easy Apply form field."""
    print("[UTOP|func|_resolve_field_value|cp-fr-014]")
    q = question_text.lower().strip()
    q_norm = " ".join(re.sub(r"[^a-z0-9]", " ", q).split())

    learned = profile.setdefault("learned_answers", {})
    if q_norm in learned:
        print(f"  [LEARNED MATCH] resolved '{question_text}' => '{learned[q_norm]}'")
        return str(learned[q_norm])

    val = _resolve_from_profile(q, profile)
    if val:
        return val

    print(f"  [AI RESOLVER] Invoking Gemini to answer: '{question_text}'...")
    ai_answer = _resolve_via_gemini(question_text, profile, cv_text)

    is_interactive = sys.stdout.isatty() and sys.stdin.isatty()
    suggestion = (
        ai_answer
        if ai_answer
        else str(profile.get("experience_years", {}).get("_default", 3))
    )

    if is_interactive:
        final_answer = _get_interactive_screening_answer(question_text, suggestion)
    else:
        final_answer = suggestion
        if not ai_answer:
            print(
                f"  [WARNING] Unattended mode and no AI answer. Falling back to default: {final_answer}"
            )

    _save_learned_answer(profile, profile_path, q_norm, final_answer, question_text)
    return final_answer


def _fill_text_inputs(page, applicant_profile, cv_text, profile_path):
    """Auto-fills all empty visible text, tel, and number inputs."""
    text_inputs = page.locator(
        'input[type="text"]:not([readonly]), input[type="tel"]:not([readonly]), input[type="number"]:not([readonly])'
    )
    for ti in text_inputs.all():
        try:
            if not ti.is_visible() or not ti.is_enabled():
                continue
            if ti.input_value() == "":
                question_text = ti.evaluate("""el => {
                    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
                    if (el.id) {
                        const lbl = document.querySelector('label[for="' + el.id + '"]');
                        if (lbl) return lbl.innerText.trim();
                    }
                    let parent = el.parentElement;
                    for (let i = 0; i < 5 && parent; i++) {
                        const lbl = parent.querySelector('label, legend, .fb-dash-form-element__label, .artdeco-text-input--label, span[aria-hidden="true"]');
                        if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
                        parent = parent.parentElement;
                    }
                    return el.getAttribute('placeholder') || '';
                }""")
                if any(k in question_text.lower() for k in ["language", "ngôn ngữ"]):
                    fill_value = "English"
                    ti.fill(fill_value)
                    try:
                        time.sleep(1)
                        typeahead = page.locator('.search-typeahead-v2__hit, [data-test-single-typeahead-entity-form-search-result="true"], .typeahead-result').first
                        if typeahead.count() > 0 and typeahead.is_visible():
                            typeahead.click()
                            time.sleep(0.5)
                    except Exception:
                        pass
                else:
                    fill_value = _resolve_field_value(
                        question_text, applicant_profile, cv_text, profile_path
                    )
                    ti.fill(fill_value)
                print(f"  Auto-filled '{question_text}' => {fill_value}")

                # Select typeahead suggestion or dismiss overlay
                if any(k in question_text.lower() for k in ["city", "location", "địa điểm", "thành phố"]):
                    try:
                        time.sleep(1)
                        typeahead = page.locator('.search-typeahead-v2__hit, [data-test-single-typeahead-entity-form-search-result="true"], .typeahead-result').first
                        if typeahead.count() > 0 and typeahead.is_visible():
                            typeahead.click()
                            time.sleep(0.5)
                        else:
                            ti.press("Escape")
                    except Exception:
                        pass
        except Exception as e:
            print(f"  [ERROR] Failed to auto-fill text field: {e}")


def _fill_dropdowns(page):
    """Auto-selects first option of any dropdowns."""
    selects = page.locator("select")
    for sel in selects.all():
        try:
            if sel.is_visible() and sel.is_enabled():
                options = sel.locator("option").all()
                if len(options) > 1 and sel.evaluate("el => el.selectedIndex") == 0:
                    sel.select_option(index=1)
                    print("  Auto-selected dropdown option")
        except:
            pass


def _fill_radios(page):
    """Auto-checks the first option (preferring 'Yes') of any radio groups."""
    try:
        radios = page.locator('input[type="radio"]').all()
        seen_groups = set()
        for r in radios:
            try:
                name = r.get_attribute("name") or "default_group"
                if name in seen_groups:
                    continue
                # Check if this group already has a checked radio
                group_members = [rm for rm in radios if rm.get_attribute("name") == name]
                if any(rm.is_checked() for rm in group_members):
                    seen_groups.add(name)
                    continue

                # Find preferred 'Yes' radio or use first member
                target_radio = None
                for rm in group_members:
                    val = (rm.get_attribute("value") or "").lower()
                    lbl = (rm.evaluate("el => el.parentElement ? el.parentElement.innerText : ''") or "").lower()
                    if any(y in val or y in lbl for y in ["yes", "có", "agree", "authorized", "eligible"]):
                        target_radio = rm
                        break
                if target_radio is None and group_members:
                    target_radio = group_members[0]

                if target_radio is not None:
                    try:
                        target_radio.check(force=True)
                    except Exception:
                        target_radio.locator("xpath=..").click(force=True)
                    seen_groups.add(name)
                    print(f"  Auto-checked radio in group: {name[:30]}")
            except Exception:
                pass
    except Exception as e:
        print(f"  [WARNING] Failed to fill radio groups: {e}")


def _fill_checkboxes(page):
    """Auto-checks any unchecked checkboxes."""
    try:
        checkboxes = page.locator('input[type="checkbox"]').all()
        for cb in checkboxes:
            try:
                if cb.is_visible() and not cb.is_checked():
                    try:
                        cb.check(force=True)
                    except Exception:
                        cb.locator("xpath=..").click(force=True)
                    print("  Auto-checked checkbox (forced)")
            except Exception:
                pass
    except Exception as e:
        print(f"  [WARNING] Failed to fill checkboxes: {e}")


def _fill_dropdowns_and_radios(page):
    """Auto-selects dropdowns, radio button groups, and checkboxes."""
    _fill_dropdowns(page)
    _fill_radios(page)
    _fill_checkboxes(page)


def _upload_cv_external(page, cv_path):
    """Uploads the tailored CV PDF to file inputs on external site."""
    if not cv_path or not os.path.exists(cv_path):
        return False
    selectors = [
        'input[type="file"][id*="resume" i]',
        'input[type="file"][id*="cv" i]',
        'input[type="file"][name*="resume" i]',
        'input[type="file"][name*="cv" i]',
        'input[type="file"][accept*="pdf" i]',
        'input[type="file"]',
    ]
    for sel in selectors:
        try:
            inp = page.locator(sel).first
            if inp.count() > 0:
                inp.set_input_files(cv_path)
                print(
                    f"  [EXTERNAL] Attached CV using selector '{sel}': {os.path.basename(cv_path)}"
                )
                return True
        except Exception as e:
            print(f"  [WARNING] Upload CV failed on '{sel}': {e}")
    return False


def _fill_inputs_external(page, profile, cv_text, profile_path):
    """Fills visible text inputs and textareas on external pages."""
    selectors = [
        'input[type="text"]:not([readonly])',
        'input[type="email"]:not([readonly])',
        'input[type="tel"]:not([readonly])',
        'input[type="number"]:not([readonly])',
        'input[type="url"]:not([readonly])',
        "input:not([type]):not([readonly])",
        "textarea:not([readonly])",
    ]
    inputs = page.locator(", ".join(selectors))
    for i in range(inputs.count()):
        try:
            inp = inputs.nth(i)
            if not inp.is_visible() or not inp.is_enabled() or inp.input_value() != "":
                continue
            lbl = inp.evaluate("""el => {
                if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
                if (el.id) {
                    const lbl = document.querySelector('label[for="' + el.id + '"]');
                    if (lbl) return lbl.innerText.trim();
                }
                let parent = el.parentElement;
                for (let i = 0; i < 5 && parent; i++) {
                    const lbl = parent.querySelector('label, legend, .label, .field-label, span[class*="label"]');
                    if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
                    parent = parent.parentElement;
                }
                return el.getAttribute('placeholder') || el.getAttribute('name') || '';
            }""")
            if lbl:
                val = _resolve_field_value(lbl, profile, cv_text, profile_path)
                if val:
                    inp.fill(val)
                    print(f"  [EXTERNAL] Auto-filled '{lbl}' => '{val}'")
        except Exception as e:
            print(f"  [WARNING] Failed to fill input: {e}")


def _extract_sitekey(page):
    # Try finding hCaptcha elements in main page
    try:
        hcap_el = page.locator(".h-captcha").first
        if hcap_el.count() > 0:
            key = hcap_el.get_attribute("data-sitekey") or hcap_el.get_attribute(
                "data-key"
            )
            if key:
                return "hcaptcha", key
    except Exception:
        pass

    # Try finding Turnstile elements in main page
    try:
        cf_el = page.locator(".cf-turnstile").first
        if cf_el.count() > 0:
            key = cf_el.get_attribute("data-sitekey") or cf_el.get_attribute("data-key")
            if key:
                return "turnstile", key
    except Exception:
        pass

    # Try scanning all frames (iframes) for hcaptcha or turnstile URLs
    try:
        import urllib.parse

        for frame in page.frames:
            url = frame.url
            if "hcaptcha.com" in url:
                parsed = urllib.parse.urlparse(url)
                params = urllib.parse.parse_qs(parsed.query or parsed.fragment)
                sitekey = params.get("sitekey", [None])[0]
                if not sitekey and parsed.fragment:
                    frag_params = urllib.parse.parse_qs(parsed.fragment)
                    sitekey = frag_params.get("sitekey", [None])[0]
                if sitekey:
                    return "hcaptcha", sitekey
            if "challenges.cloudflare.com" in url:
                parsed = urllib.parse.urlparse(url)
                params = urllib.parse.parse_qs(parsed.query or parsed.fragment)
                sitekey = params.get("sitekey", [None])[0]
                if sitekey:
                    return "turnstile", sitekey
    except Exception:
        pass

    return None, None


def _try_resolve_captcha(page, job) -> bool:
    try:
        captcha_type, sitekey = _extract_sitekey(page)
        if not sitekey:
            print("  [CAPTCHA] No hCaptcha or Turnstile sitekey could be extracted.")
            return False

        print(f"  [CAPTCHA] Extracted {captcha_type} sitekey: {sitekey}")

        # Initialize solver
        from core.captcha_solver import (
            CaptchaSolver,
            inject_hcaptcha_token,
            inject_turnstile_token,
        )

        solver = CaptchaSolver()
        if not solver.api_key:
            print("  [CAPTCHA] Solver API key is missing. Skipping auto-solve.")
            return False

        print(f"  [CAPTCHA] Solving {captcha_type} using {solver.service}...")
        if captcha_type == "hcaptcha":
            token = solver.solve_hcaptcha(page.url, sitekey)
            inject_hcaptcha_token(page, token)
            print("  [CAPTCHA] hCaptcha token injected successfully!")
        elif captcha_type == "turnstile":
            token = solver.solve_turnstile(page.url, sitekey)
            inject_turnstile_token(page, token)
            print("  [CAPTCHA] Turnstile token injected successfully!")
        else:
            return False

        # Wait a short duration for the form/verification wrapper to process the token
        page.wait_for_timeout(3000)
        return True
    except Exception as solve_err:
        print(f"  [CAPTCHA ERROR] Failed during automated solving: {solve_err}")
        return False


def parse_llm_visual_action(text: str) -> tuple[dict, str]:
    """
    Parses LLM response for visual applying action.
    Supports JSON, Markdown fenced JSON, key-value markdown format, and conversational completion detection.
    Returns (action_cmd_dict, error_message).
    """
    if not text or not text.strip():
        return {}, "Empty or blank LLM response"

    cleaned = text.strip()

    # 1. Try parsing JSON (fenced or direct)
    json_candidate = cleaned
    if "```" in json_candidate:
        json_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", json_candidate)
        if json_match:
            json_candidate = json_match.group(1).strip()
        else:
            json_candidate = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", json_candidate, flags=re.DOTALL
            ).strip()

    if "{" in json_candidate and "}" in json_candidate:
        try:
            start = json_candidate.find("{")
            end = json_candidate.rfind("}")
            parsed = json.loads(json_candidate[start : end + 1])
            if isinstance(parsed, dict) and "action" in parsed:
                return parsed, ""
        except json.JSONDecodeError:
            pass

    # 2. Check for conversational submission confirmation
    lower_text = cleaned.lower()
    if (
        "successfully submitted" in lower_text
        or "confirmation page" in lower_text
        or "application is submitted" in lower_text
        or "submission confirmation" in lower_text
    ):
        return {
            "action": "done",
            "reasoning": "Detected application completion confirmation in response.",
        }, ""

    # 3. Try parsing Markdown key-values: e.g. **Action:** type, **Selector:** ...
    kv_pattern = re.compile(
        r"\*\*(Action|Selector|Value|Reasoning):\*\*\s*(.+)", re.IGNORECASE
    )
    matches = kv_pattern.findall(cleaned)
    if matches:
        cmd = {}
        for k, v in matches:
            cmd[k.lower().strip()] = v.strip()
        if "action" in cmd:
            return cmd, ""

    return {}, f"Could not parse action from response: {cleaned[:100]}"


def _agentic_external_apply(
    page, job, dirs, cv_file, tailored_cvs, profile, cv_text, profile_path, dry_run
):
    import base64
    import json
    import time

    from dotenv import load_dotenv

    def save_fail_screenshot(status_name):
        proof_file = os.path.join(
            dirs["proof_dir"],
            f"external_{status_name}_{safe_filename(job['company'])}__{job['id']}.png",
        )
        try:
            target_page = page
            if hasattr(target_page, "is_closed") and target_page.is_closed():
                context = getattr(target_page, "context", None)
                if context and context.pages:
                    active_pages = [p for p in context.pages if not p.is_closed()]
                    if active_pages:
                        target_page = active_pages[-1]
            if hasattr(target_page, "is_closed") and not target_page.is_closed():
                target_page.screenshot(path=proof_file)
                job["proof_path"] = proof_file
                print(
                    f"  [SCREENSHOT] Captured external {status_name} screenshot: {proof_file}"
                )
        except Exception as se:
            print(f"  [WARNING] Failed to capture external screenshot: {se}")

    load_dotenv()

    print(f"  [AGENT] Starting visual agent loop for {job['company']}...")
    cv_pdf = tailored_cvs.get(job["id"], cv_file) if tailored_cvs else cv_file
    action_history = []

    # Load dynamic self-healed field answers and remediated selectors
    dynamic_answers = {}
    remediated_selectors = {}
    for base_p in [Path(__file__).resolve().parent.parent / "data", Path(r".\data")]:
        ans_f = base_p / "dynamic_field_answers.json"
        sel_f = base_p / "remediated_selectors.json"
        try:
            if ans_f.exists() and not dynamic_answers:
                with open(ans_f, "r", encoding="utf-8") as f:
                    dynamic_answers = json.load(f)
            if sel_f.exists() and not remediated_selectors:
                with open(sel_f, "r", encoding="utf-8") as f:
                    remediated_selectors = json.load(f)
        except Exception:
            pass

    if dry_run:
        print("  [AGENT] Running in Dry Run mode - will intercept final submission.")

    for step in range(35):
        time.sleep(3)
        try:
            # Multi-page / Popup Tab context switch & auto re-attachment
            context = getattr(page, "context", None)
            if context and context.pages:
                active_pages = [p for p in context.pages if not p.is_closed()]
                if active_pages:
                    if (hasattr(page, "is_closed") and page.is_closed()) or (len(active_pages) > 1 and page != active_pages[-1]):
                        page = active_pages[-1]
                        print(f"  [AGENT] Switched / Attached to active tab: {page.url}")
                else:
                    print("  [AGENT ERROR] All browser pages closed.")
                    break

            if hasattr(page, "is_closed") and page.is_closed():
                break

            page.wait_for_load_state("domcontentloaded", timeout=15000)
            try:
                if "linkedin.com" not in page.url:
                    page.keyboard.press("Escape")
            except:
                pass
            page.evaluate("""() => {
                for (let selector of ['#onetrust-consent-sdk', '.onetrust-pc-dark-filter', '.ot-sdk-container', '#onetrust-banner-sdk', '#consent-banner', '.cookie-consent', '#cookie-banner', '#cookie-consent-banner', '#glints-portal-container', 'div[class*="ModalStyle__StyledModalWrapper"]']) {
                    try {
                        let el = document.querySelector(selector);
                        if (el) el.remove();
                    } catch(e) {}
                }
                try {
                    document.body.style.pointerEvents = 'auto';
                    document.documentElement.style.pointerEvents = 'auto';
                } catch(e) {}
            }""")
        except:
            pass

        # Programmatic platform-specific dialog bypasses
        if hasattr(page, "url") and "vietnamworks.com" in page.url:
            try:
                handled = page.evaluate("""() => {
                    let replaceBtn = Array.from(document.querySelectorAll('button, div')).find(
                        el => el.innerText && (el.innerText.includes('Thay thế') || el.innerText.includes('Replace'))
                    );
                    if (replaceBtn) {
                        let radio = document.querySelector('input[type="radio"], .radio-button');
                        if (radio) {
                            radio.click();
                            return new Promise(resolve => {
                                setTimeout(() => {
                                    replaceBtn.click();
                                    resolve(true);
                                }, 500);
                            });
                        }
                    }
                    return false;
                }""")
                if handled:
                    print(
                        "  [AGENT] Handled VietnamWorks 3-CV limit popup programmatically."
                    )
                    time.sleep(2)
            except Exception as e:
                print(
                    f"  [AGENT DEBUG] Failed to handle VietnamWorks popup programmatically: {e}"
                )

        # Check for CAPTCHA or Bot detection challenge
        try:
            body_text = ""
            try:
                body_text = page.locator("body").inner_text().lower()
            except Exception:
                pass

            has_captcha = False
            if any(
                term in body_text
                for term in [
                    "confirm you are human",
                    "please verify you are human",
                    "verify you are human",
                    "checking your browser",
                ]
            ):
                has_captcha = True
            else:
                sitekey, captcha_type = _extract_sitekey(page)
                if sitekey:
                    try:
                        if (
                            page.locator(".h-captcha").is_visible()
                            or page.locator(".cf-turnstile").is_visible()
                        ):
                            has_captcha = True
                        else:
                            for frame in page.frames:
                                if (
                                    "hcaptcha.com" in frame.url
                                    or "challenges.cloudflare.com" in frame.url
                                ):
                                    frame_el = frame.frame_element()
                                    if frame_el and frame_el.is_visible():
                                        has_captcha = True
                                        break
                    except Exception:
                        pass

            if has_captcha:
                print("  [AGENT] CAPTCHA or Bot detection challenge detected!")
                # Try to auto-resolve first!
                resolved = _try_resolve_captcha(page, job)
                if resolved:
                    print(
                        "  [AGENT] CAPTCHA solver finished. Checking if blocker cleared..."
                    )
                    # Re-read page content to see if terms are still present
                    page.wait_for_timeout(2000)
                    html_content = page.content().lower()
                    if not any(
                        term in html_content
                        for term in [
                            "captcha",
                            "hcaptcha",
                            "recaptcha",
                            "cloudflare turnstile",
                            "confirm you are human",
                            "please verify you are human",
                        ]
                    ):
                        print("  [AGENT] Blocker cleared! Continuing flow.")
                    else:
                        print(
                            "  [AGENT] Blocker still present after auto-solving attempt."
                        )
                        job["apply_status"] = "External (Manual Required)"
                        job["manual_intervention_reason"] = (
                            "CAPTCHA auto-solving succeeded but page blocker was not cleared"
                        )
                        save_fail_screenshot("captcha_stuck")
                        return
                else:
                    job["apply_status"] = "External (Manual Required)"
                    job["manual_intervention_reason"] = (
                        "CAPTCHA or Bot detection challenge detected (auto-solve failed/unconfigured)"
                    )
                    save_fail_screenshot("captcha")
                    return
        except Exception as e:
            print(
                f"  [AGENT WARNING] Failed to read page content for captcha check: {e}"
            )

        try:
            # Check for standard success indicators on the page
            try:
                page_text = page.locator("body").inner_text().lower()
                success_indicators = [
                    "thank you for your submission",
                    "thank you for submitting",
                    "application submitted",
                    "application received",
                    "submission received",
                    "successfully submitted",
                    "thanks for applying",
                    "nộp đơn thành công",
                    "cảm ơn bạn đã nộp đơn",
                ]
                if any(indicator in page_text for indicator in success_indicators):
                    print(
                        "  [AGENT] Detected submission success text on the page! Marking as done."
                    )
                    success_proof = os.path.join(
                        dirs["proof_dir"],
                        f"external_submitted_{safe_filename(job['company'])}__{job['id']}.png",
                    )
                    page.screenshot(path=success_proof)
                    job["proof_path"] = success_proof
                    job["apply_status"] = "Success (Submitted)"
                    return
            except Exception as e_success_check:
                print(
                    f"  [AGENT DEBUG] Error checking for success page text: {e_success_check}"
                )

            # Take screenshot
            screenshot_bytes = page.screenshot(type="jpeg", quality=80)
            b64_image = base64.b64encode(screenshot_bytes).decode("utf-8")

            interactive_dom = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('input, button, select, textarea, a, label, [role="combobox"], [role="listbox"], [role="option"], [role="radio"], [role="checkbox"], .select2-selection, .select-choice')).map((el, idx) => {
                    let rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return null;
                    let text = el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.name || el.id || '';
                    return {
                        index: idx,
                        tag: el.tagName,
                        type: el.type || '',
                        id: el.id || '',
                        name: el.name || '',
                        checked: el.checked || false,
                        disabled: el.disabled || false,
                        placeholder: el.placeholder || '',
                        aria_label: el.getAttribute('aria-label') || '',
                        text: text.trim().substring(0, 100)
                    };
                }).filter(e => e && (e.text || e.id || e.name || ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(e.tag)));
            }""")

            recent_actions_summary = [
                f"Step {a['step']}: {a['action'].upper()} on '{a['selector']}' (val: '{a['value']}')"
                for a in action_history[-4:]
            ]

            prompt = f"""You are an autonomous AI web agent filling out a job application.
I have provided a screenshot of the current page and a JSON list of interactive DOM elements.

Current Page URL: {page.url}

Profile Data:
{json.dumps(profile, indent=2)}

Dynamic Remediated Field Answers:
{json.dumps(dynamic_answers, indent=2)}

Remediated Platform Selectors:
{json.dumps(remediated_selectors, indent=2)}

CV Text Snippet:
{cv_text[:1000]}

DOM Elements:
{json.dumps(interactive_dom, indent=2)}

Recent Actions Taken:
{json.dumps(recent_actions_summary, indent=2)}

Determine the NEXT action to take to progress the application.
CRITICAL INSTRUCTIONS:
1. If an input or question was already answered/clicked in Recent Actions, DO NOT click/type it again. Move to the NEXT question or click Next/Submit.
2. If multiple questions have "Yes/No" options, identify distinct questions by their unique name or label container.
3. If an input matches a pattern in Dynamic Remediated Field Answers, use the exact synthesized value provided.
4. If the application is successfully submitted and you see a confirmation page, return action "done".
5. If you are stuck or repeatedly looping, return action "fail".

Return ONLY a valid JSON object matching this schema:
{{
  "action": "type" | "click" | "upload" | "done" | "fail",
  "selector": "CSS selector to target the element (e.g. '#firstName' or 'input[name=lastName]') or Playwright-compatible text selector (e.g. 'text=\"Apply Now\"' or 'a:has-text(\"Apply Now\")')",
  "value": "The text to type (if action is type)",
  "reasoning": "Brief explanation of why"
}}
"""
            try:
                client = GeminiClient()
                llm_text = client.call(prompt, json_mode=True, image_b64=b64_image)
            except Exception as req_err:
                print(f"  [AGENT WARNING] Antigravity CLI call failed: {req_err}.")
                llm_text = '{"action": "fail", "reasoning": "CLI call failed."}'

            cmd, parse_err = parse_llm_visual_action(llm_text)
            if parse_err:
                print(f"  [AGENT WARNING] Parse error: {parse_err}. Continuing loop...")
                continue

            action = cmd.get("action")
            selector = cmd.get("selector")
            value = cmd.get("value")
            reason = cmd.get("reasoning", "")

            if selector and isinstance(selector, str):
                if selector in remediated_selectors:
                    healed_sel = remediated_selectors[selector]
                    print(f"  [AGENT HEALED SELECTOR] Overriding '{selector}' with remediated locator: '{healed_sel}'")
                    selector = healed_sel

                import re

                # Convert ID selectors starting with a digit (invalid in querySelectorAll) to [id="..."]
                selector = re.sub(r"#(\d[\w\-]*)", r'[id="\1"]', selector)

                def repl(match):
                    key = match.group(1)
                    val = match.group(2)
                    if any(
                        c in val
                        for c in ["[", "]", "-", ".", ":", "/", "@", "$", "#", "*"]
                    ):
                        return f'[{key}="{val}"]'
                    return match.group(0)

                selector = re.sub(r"\[(\w+)=([^\'\"\]]+)\]", repl, selector)

            if not action:
                print(
                    "  [AGENT WARNING] LLM response is missing the 'action' key. Continuing loop..."
                )
                continue

            if isinstance(action, dict):
                nested_sel = action.get("selector")
                if nested_sel and not selector:
                    selector = nested_sel
                nested_val = action.get("value")
                if nested_val and not value:
                    value = nested_val
                action = (
                    action.get("type")
                    or action.get("action")
                    or action.get("name")
                    or str(action)
                )
            action = str(action).strip().lower()

            print(
                f"  [AGENT] {action.upper()} | {selector} | {value} | Reason: {reason}"
            )

            # Record action in history
            action_history.append({"action": action, "selector": selector, "value": value, "step": step})

            if action == "done":
                print("  [AGENT] Successfully completed application!")

                success_proof = os.path.join(
                    dirs["proof_dir"],
                    f"external_submitted_{safe_filename(job['company'])}__{job['id']}.png",
                )
                page.screenshot(path=success_proof)
                job["proof_path"] = success_proof
                job["apply_status"] = (
                    "Success (Dry Run)" if dry_run else "Success (Submitted)"
                )
                return
            elif action == "fail":
                print("  [AGENT] Stuck. Falling back to manual.")
                job["apply_status"] = "External (Manual Required)"
                job["manual_intervention_reason"] = (
                    "Visual agent got stuck or reported failure during form-filling"
                )
                save_fail_screenshot("stuck")
                return
            elif dry_run and action == "click" and selector:
                # Check if this click action is a true final submission click (NOT initial opening button)
                is_submit_click = False
                initial_open_keywords = [
                    "apply for this job",
                    "apply on employer site",
                    "apply on company website",
                    "apply now",
                    "easy apply",
                    "ứng tuyển ngay",
                    "nộp đơn ngay",
                    "start application",
                    "open application",
                ]
                final_submit_keywords = [
                    "submit application",
                    "submit your application",
                    "review and submit",
                    "complete application",
                    "final submit",
                    "xác nhận nộp đơn",
                    "gửi hồ sơ ứng tuyển",
                ]
                try:
                    target_el = page.locator(selector).first
                    if target_el.count() > 0:
                        btn_text = target_el.inner_text().strip().lower()
                        # Strict check: NEVER intercept initial opening buttons
                        if not any(ik in btn_text for ik in initial_open_keywords):
                            # Intercept if strict final submit keywords match
                            if any(fk in btn_text for fk in final_submit_keywords):
                                is_submit_click = True
                            # Or if single submit word AND we have performed field-filling actions
                            elif any(sk in btn_text for sk in ["submit", "gửi", "nộp đơn"]) and (step > 1 or len(action_history) > 1):
                                is_submit_click = True
                except Exception as ce:
                    print(
                        f"  [AGENT DEBUG] Failed to inspect element text for dry-run check: {ce}"
                    )

                if is_submit_click:
                    print(
                        f"  [DRY RUN] Intercepted FINAL submission click on selector: {selector} (Step: {step})"
                    )
                    dry_run_proof = os.path.join(
                        dirs["proof_dir"],
                        f"external_dryrun_{safe_filename(job['company'])}__{job['id']}.png",
                    )
                    page.screenshot(path=dry_run_proof)
                    job["proof_path"] = dry_run_proof
                    job["apply_status"] = "Success (Dry Run)"
                    return

            try:
                if action == "type":
                    if not selector:
                        print("  [AGENT WARNING] Type action missing selector. Continuing...")
                        continue
                    value_to_type = str(value) if value is not None else ""
                    loc = page.locator(selector)
                    visible_loc = loc.filter(visible=True)
                    target = visible_loc.first if visible_loc.count() > 0 else loc.first
                    try:
                        target.scroll_into_view_if_needed(timeout=5000)
                        target.click(timeout=5000)
                    except Exception as e:
                        print(f"  [AGENT WARNING] Failed to focus input: {e}")
                    # Humanized typing: clear existing text, then type character by character
                    try:
                        target.fill("", timeout=4000)
                        import random

                        page.wait_for_timeout(random.randint(150, 400))
                        target.type(value_to_type, delay=random.randint(40, 120))
                    except Exception:
                        target.fill(value_to_type, timeout=8000)
                elif action == "click":
                    if not selector or not str(selector).strip():
                        # Try to resolve selector from reasoning or common apply buttons
                        print(f"  [AGENT] Click missing selector. Attempting fallback text match from reasoning: {reason}")
                        found_target = None
                        fallback_keywords = ["nộp đơn", "apply", "ứng tuyển", "submit", "next", "tiếp tục", "gửi"]
                        for kw in fallback_keywords:
                            if kw in (reason or "").lower():
                                cand = page.locator(f'button:has-text("{kw}"), a:has-text("{kw}"), input[value*="{kw}" i]').filter(visible=True)
                                if cand.count() > 0:
                                    found_target = cand.first
                                    print(f"  [AGENT FALLBACK] Resolved click target using keyword '{kw}'")
                                    break
                        if found_target:
                            target = found_target
                        else:
                            print("  [AGENT WARNING] Click action missing valid selector. Continuing loop...")
                            continue
                    else:
                        import re

                        selector_stripped = str(selector).strip()
                        m = re.match(
                            r'^\s*(\w+)?\s*:\s*contains\(\s*[\'"]?(.*?)[\'"]?\s*\)\s*$',
                            selector_stripped,
                            re.IGNORECASE,
                        )
                        if m:
                            tag = m.group(1) or "*"
                            text = m.group(2)
                            loc = page.locator(f'{tag}:has-text("{text}")')
                        else:
                            loc = page.locator(selector)

                        visible_loc = loc.filter(visible=True)

                        # Check for loop / repeated click pattern
                        same_clicks = [
                            a for a in action_history[-4:]
                            if a.get("action") == "click" and a.get("selector") == selector
                        ]
                        repeat_count = len(same_clicks)

                        if repeat_count >= 4:
                            print(f"  [AGENT LOOP BREAKER] Target '{selector}' clicked {repeat_count} consecutive times without advancement. Breaking loop.")
                            job["apply_status"] = "External (Manual Required)"
                            job["manual_intervention_reason"] = f"Visual agent detected infinite click loop on selector: {selector}"
                            save_fail_screenshot("loop_stuck")
                            return
                        elif repeat_count >= 2 and visible_loc.count() > 1:
                            target_idx = min(repeat_count - 1, visible_loc.count() - 1)
                            print(f"  [AGENT DISAMBIGUATION] Repeated click detected. Targeting element index #{target_idx} for '{selector}'...")
                            target = visible_loc.nth(target_idx)
                        else:
                            target = visible_loc.first if visible_loc.count() > 0 else loc.first

                    # Humanized click: hover before click, small delay
                    try:
                        target.hover(timeout=4000)
                        import random

                        page.wait_for_timeout(random.randint(100, 300))
                    except Exception:
                        pass
                    try:
                        target.click(timeout=8000)
                    except Exception as click_err:
                        if "intercept" in str(click_err).lower():
                            print(
                                "  [AGENT WARNING] Click intercepted by overlay. Retrying click with force=True..."
                            )
                            target.click(force=True, timeout=8000)
                        else:
                            raise click_err
                elif action == "upload":
                    upload_sel = selector if selector and str(selector).strip() else 'input[type="file"]'
                    loc = page.locator(upload_sel)
                    visible_loc = loc.filter(visible=True)
                    if visible_loc.count() > 0:
                        visible_loc.first.set_input_files(cv_pdf, timeout=8000)
                    else:
                        loc.first.set_input_files(cv_pdf, timeout=8000)
            except Exception as action_err:
                print(
                    f"  [AGENT WARNING] Action execution failed: {action_err}. Continuing loop..."
                )

        except Exception as e:
            print(f"  [AGENT ERROR] {e}")
            job["apply_status"] = "External (Manual Required)"
            job["manual_intervention_reason"] = (
                f"Visual agent loop error: {str(e)[:200]}"
            )
            save_fail_screenshot("error")
            return

    print("  [AGENT] Hit maximum iterations (35). Stopping.")
    job["apply_status"] = "External (Manual Required)"
    job["manual_intervention_reason"] = (
        "Visual agent hit maximum iterations (35) without completing submission"
    )
    save_fail_screenshot("timeout")


def _handle_external_apply(
    page,
    context,
    job,
    dirs,
    btn_text,
    profile,
    cv_text,
    profile_path,
    tailored_cvs,
    cv_file,
    dry_run,
    apply_btn,
):
    """Handles automatic pre-filling and submission on an external application site."""
    print(f"  Detected external apply button ('{btn_text}'). Opening job page...")
    try:
        new_page = None
        try:
            with context.expect_page(timeout=12000) as new_page_info:
                apply_btn.click(force=True)
            new_page = new_page_info.value
            print("  Opened external apply page in a new tab immediately.")
        except Exception:
            new_page = None
            time.sleep(2)
            continue_btn = page.locator(
                '.artdeco-modal button:has-text("Continue"), button[aria-label*="Continue"]'
            )
            if continue_btn.count() > 0:
                print("  Detected 'Share your profile?' dialog. Clicking Continue...")
                try:
                    with context.expect_page(timeout=15000) as new_page_info:
                        continue_btn.first.click()
                    new_page = new_page_info.value
                except Exception as ce:
                    print(f"  [WARNING] Failed to open external page from dialog: {ce}")
            else:
                new_page = context.pages[-1] if len(context.pages) > 1 else None

        if not new_page:
            # Check if main tab navigated (same-tab navigation)
            current_url = page.url
            if (
                "linkedin.com/jobs" not in current_url
                and "linkedin.com/checkpoint" not in current_url
            ):
                new_page = page
                print("  Main tab navigated to external page.")

        if not new_page:
            ext_url = page.evaluate("""() => {
                const modal = document.querySelector('.artdeco-modal');
                if (modal) {
                    const link = modal.querySelector('a[href]');
                    if (link) return link.href;
                }
                return null;
            }""")
            if ext_url:
                new_page = context.new_page()
                new_page.goto(ext_url)

        if new_page:
            new_page.wait_for_load_state("domcontentloaded", timeout=15000)
            ext_url = new_page.url
            print(f"  EXTERNAL SITE OPENED: {ext_url}")
            job["external_url"] = ext_url

            _agentic_external_apply(
                new_page,
                job,
                dirs,
                cv_file,
                tailored_cvs,
                profile,
                cv_text,
                profile_path,
                dry_run,
            )

            if job["apply_status"] == "External (Manual Required)":
                print("  >> Please submit manually. Pipeline pauses for 1s...")
                time.sleep(1)
            else:
                time.sleep(2)
        else:
            raise Exception("Could not find external apply URL via modal or new tab")
    except Exception as e:
        print(f"  [WARNING] Could not open external apply page: {e}")
        job["apply_status"] = "External (Failed to Open)"
        proof_file = os.path.join(
            dirs["proof_dir"],
            f"external_failed_open_{safe_filename(job['company'])}__{job['id']}.png",
        )
        try:
            page.screenshot(path=proof_file)
            job["proof_path"] = proof_file
            print(
                f"  [SCREENSHOT] Captured external failed open screenshot: {proof_file}"
            )
        except Exception as se:
            print(f"  [WARNING] Failed to capture page screenshot: {se}")


def _fill_easy_apply_modal(
    page,
    job,
    cv_file,
    dirs,
    tailored_cvs,
    applicant_profile,
    cv_text,
    profile_path,
    dry_run,
):
    """Executes the modal interaction loop for LinkedIn Easy Apply."""
    review_click_count = 0
    page.set_default_timeout(3000)
    for step in range(35):
        time.sleep(2)

        # Handle discard confirmation dialog if present
        try:
            discard_dialog = page.locator('[data-test-modal-id="data-test-easy-apply-discard-confirmation"]')
            if discard_dialog.count() > 0 and discard_dialog.is_visible():
                cancel_discard = discard_dialog.locator('button:has-text("Cancel"), button[aria-label*="Cancel"]').first
                if cancel_discard.count() > 0:
                    cancel_discard.click()
                    time.sleep(1)
        except Exception:
            pass

        # Handle LinkedIn Job Search Safety Reminder if present
        try:
            safety_btn = page.locator(
                'button:has-text("Continue applying"), [aria-label="Continue applying"]'
            ).first
            if safety_btn.count() > 0 and safety_btn.is_visible():
                print(
                    "  [DEBUG] Found LinkedIn safety reminder modal. Clicking 'Continue applying'..."
                )
                safety_btn.click()
                time.sleep(2)
        except Exception:
            pass

        # Locate the visible modal container to scope all queries inside it
        modals = page.locator('.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]')
        modal = None
        for i in range(modals.count()):
            m = modals.nth(i)
            try:
                if m.is_visible():
                    modal = m
                    break
            except:
                pass

        if modal is None:
            if "/apply/" in page.url:
                print(
                    "  [DEBUG] Full page apply flow detected (no modal dialog). Scoping to entire page."
                )
                modal_container = page
            else:
                if step < 3:
                    print(
                        f"  [DEBUG] Modal not visible in step {step}. Retrying... (Modal might still be loading)"
                    )
                    continue
                print("  [ERROR] Easy Apply modal not visible. Exiting.")
                stuck_path = os.path.join(
                    dirs["proof_dir"], f"no_modal_{job['id']}.png"
                )
                page.screenshot(path=stuck_path)
                job["apply_status"] = "Stuck (Manual Intervention Required)"
                job["manual_intervention_reason"] = (
                    "Easy Apply modal not visible (dialog container not found)"
                )
                job["proof_path"] = stuck_path
                break
        else:
            modal_container = modal

        # Check if we are on the resume upload screen.
        file_input = modal_container.locator('input[type="file"]').first
        attached_successfully = False

        modal_text = ""
        try:
            modal_text = modal_container.inner_text().lower()
        except:
            pass

        is_resume_screen = file_input.count() > 0 and any(
            kw in modal_text
            for kw in [
                "resume",
                "cv",
                "hồ sơ",
                "curriculum vitae",
                "document",
                "tải",
                "upload",
            ]
        )

        if is_resume_screen:
            cv_pdf = tailored_cvs.get(job["id"], cv_file) if tailored_cvs else cv_file
            try:
                # Direct upload to input[type="file"]
                file_input.set_input_files(cv_pdf)
                print(
                    f"  Attached {os.path.basename(cv_pdf)} directly via file input!",
                    flush=True,
                )
                attached_successfully = True
                time.sleep(2)
            except Exception as e:
                print(
                    f"  Direct upload failed: {e}. Trying fallback selectors...",
                    flush=True,
                )

        if not attached_successfully:
            # Fallback: search for a visible upload button/label
            upload_btn_selectors = [
                'label[for*="upload-input"]',
                'label[for*="upload-button"]',
                ".jobs-document-upload__upload-button",
                'button:has-text("Upload resume")',
                'label:has-text("Upload resume")',
                'button:has-text("Upload document")',
                'label:has-text("Upload document")',
                'label:has-text("Tải hồ sơ lên")',
                'label:has-text("Tải CV lên")',
                'label:has-text("Tải hồ sơ")',
                'label:has-text("Tải CV")',
            ]
            upload_btn = None
            for sel in upload_btn_selectors:
                try:
                    locator = modal_container.locator(sel).first
                    if locator.count() > 0 and locator.is_visible():
                        upload_btn = locator
                        break
                except:
                    pass

            if upload_btn is not None:
                cv_pdf = (
                    tailored_cvs.get(job["id"], cv_file) if tailored_cvs else cv_file
                )
                try:
                    with page.expect_file_chooser(timeout=8000) as fc_info:
                        upload_btn.click(force=True)
                    file_chooser = fc_info.value
                    file_chooser.set_files(cv_pdf)
                    print(
                        f"  Attached {os.path.basename(cv_pdf)} via file chooser!",
                        flush=True,
                    )
                    attached_successfully = True
                    time.sleep(2)
                except Exception as e:
                    print(f"  Failed to attach CV via fallback button: {e}", flush=True)

        _fill_text_inputs(modal_container, applicant_profile, cv_text, profile_path)
        _fill_dropdowns_and_radios(modal_container)

        # Check and click inner card Save button if present (e.g. language card)
        try:
            inner_save = modal_container.locator('button:has-text("Save"), button:has-text("Lưu")').first
            if inner_save.count() > 0 and inner_save.is_visible():
                inner_save.click(timeout=3000)
                time.sleep(1)
        except Exception:
            pass

        submit_btn = modal_container.locator(
            'button[aria-label*="Submit application"], button:has-text("Submit application"), button:has-text("Submit"), button:has-text("Gửi hồ sơ ứng tuyển"), button:has-text("Gửi hồ sơ"), button:has-text("Nộp hồ sơ"), button:has-text("Nộp đơn")'
        ).first
        review_btn = modal_container.locator(
            'button[aria-label*="Review your application"], button:has-text("Review your application"), button:has-text("Review"), button:has-text("Xem lại đơn ứng tuyển"), button:has-text("Xem lại")'
        ).first
        next_btn = modal_container.locator(
            'button[aria-label*="Continue to next step"], button:has-text("Continue to next step"), button:has-text("Next"), button:has-text("Tiếp theo"), button:has-text("Tiếp tục")'
        ).first

        # Dismiss any open typeahead dropdown before clicking action buttons
        try:
            typeahead = modal_container.locator('.search-typeahead-v2__hit, [data-test-single-typeahead-entity-form-search-result="true"]').first
            if typeahead.count() > 0 and typeahead.is_visible():
                typeahead.click()
                time.sleep(1)
            else:
                page.keyboard.press("Escape")
        except Exception:
            pass

        if submit_btn.count() > 0 and submit_btn.is_visible():
            if dry_run:
                proof_path = os.path.join(
                    dirs["proof_dir"],
                    f"external_dryrun_{safe_filename(job['company'])}__{job['id']}.png",
                )
                page.screenshot(path=proof_path)
                job["apply_status"] = "Success (Dry Run)"
                job["proof_path"] = proof_path
                print("  [DRY RUN] Final Easy Apply submit stage reached and verified.")
            else:
                try:
                    submit_btn.click(timeout=5000)
                except Exception:
                    submit_btn.click(force=True, timeout=5000)
                
                # Active post-submission confirmation detection loop (up to 10s)
                confirmation_detected = False
                for _ in range(10):
                    time.sleep(1)
                    try:
                        body_text = page.locator("body").inner_text().lower()
                        if any(k in body_text for k in ["application submitted", "your application was sent", "thank you for applying", "đã nộp đơn", "ứng tuyển thành công"]):
                            confirmation_detected = True
                            break
                        if modal_container.count() == 0 or not modal_container.is_visible():
                            confirmation_detected = True
                            break
                    except Exception:
                        pass
                
                if confirmation_detected:
                    proof_path = os.path.join(
                        dirs["proof_dir"], f"proof_submitted_{job['id']}.png"
                    )
                    page.screenshot(path=proof_path)
                    job["proof_path"] = proof_path
                    job["apply_status"] = "Success (Submitted)"
                    print("  [SUCCESS] Application submission verified via post-submit confirmation banner!")
                else:
                    proof_path = os.path.join(
                        dirs["proof_dir"], f"proof_unconfirmed_{job['id']}.png"
                    )
                    page.screenshot(path=proof_path)
                    job["proof_path"] = proof_path
                    job["apply_status"] = "Failed (Confirmation Timeout)"
                    job["manual_intervention_reason"] = "Submit button clicked but explicit confirmation banner not detected within 10s."
                    print("  [WARNING] Submit clicked but confirmation banner was not detected.")
            break

        elif review_btn.count() > 0 and review_btn.is_visible():
            if review_click_count >= 2:
                stuck_path = os.path.join(dirs["proof_dir"], f"stuck_{job['id']}.png")
                page.screenshot(path=stuck_path)
                job["apply_status"] = "Stuck (Manual Intervention Required)"
                # Extract validation error messages
                error_msg = "Form validation failed on mandatory fields"
                try:
                    error_el = page.locator(
                        ".artdeco-inline-feedback--error, .fb-form-element__error-message"
                    ).first
                    if error_el.count() > 0:
                        error_msg = error_el.inner_text().strip()
                except Exception:
                    pass
                job["manual_intervention_reason"] = (
                    f"Easy Apply validation failed: {error_msg}"
                )
                job["proof_path"] = stuck_path
                print(
                    f"  [STUCK] Stuck on review step due to: {error_msg}. Please submit manually."
                )
                break
            try:
                review_btn.click(timeout=5000)
            except Exception:
                review_btn.click(force=True, timeout=5000)
            review_click_count += 1
        elif next_btn.count() > 0 and next_btn.is_visible():
            try:
                next_btn.click(timeout=5000)
            except Exception:
                next_btn.click(force=True, timeout=5000)
            review_click_count = 0
        else:
            if step < 3:
                print(
                    f"  [DEBUG] No action buttons found in step {step}. Retrying... (Modal might still be loading)"
                )
                time.sleep(2)
                continue
            stuck_path = os.path.join(
                dirs["proof_dir"], f"unrecognized_{job['id']}.png"
            )
            page.screenshot(path=stuck_path)
            job["apply_status"] = "Stuck (Manual Intervention Required)"
            job["manual_intervention_reason"] = (
                "Easy Apply modal navigation stuck (no Next/Review/Submit buttons found)"
            )
            job["proof_path"] = stuck_path
            print("  [UNRECOGNIZED] No action buttons found. Breaking out of loop.")
            break


def _apply_topcv(page, job, dirs, cv_file, tailored_cvs, applicant_profile, cv_text, profile_path, dry_run):
    """Dedicated native modal application handler for TopCV."""
    print(f"  [TopCV Native Apply] Starting application for {job['title']} at {job['company']}...")
    cv_pdf = tailored_cvs.get(job["id"], cv_file) if tailored_cvs else cv_file

    # 1. Check already applied
    if check_already_applied(page, job, dirs):
        return

    # 2. Check closed
    if check_job_closed(page, job, dirs):
        return

    # 3. Locate apply button
    apply_btn = None
    apply_selectors = [
        'button:has-text("Ứng tuyển ngay")',
        'a:has-text("Ứng tuyển ngay")',
        'button:has-text("Ứng tuyển")',
        'a:has-text("Ứng tuyển")',
        '.btn-apply',
        '.box-apply a',
        '#btn-apply-job',
        '.btn-apply-job',
    ]
    for sel in apply_selectors:
        candidates = page.locator(sel)
        for i in range(candidates.count()):
            c = candidates.nth(i)
            if c.is_visible() and c.is_enabled():
                apply_btn = c
                break
        if apply_btn:
            break

    if not apply_btn:
        print("  [TopCV] No apply button found. Falling back to agentic apply...")
        _agentic_external_apply(page, job, dirs, cv_file, tailored_cvs, applicant_profile, cv_text, profile_path, dry_run)
        return

    print("  [TopCV] Found apply button. Clicking to open application modal...")
    try:
        apply_btn.click()
        time.sleep(3)
    except Exception as ce:
        print(f"  [TopCV] Click apply button failed: {ce}")

    # Check if modal opened
    modal_container = page.locator('.modal-apply, #modal-apply-job, .modal-content, [class*="modal-apply"], form#form-apply')
    if modal_container.count() == 0:
        modal_container = page

    # Upload CV file
    file_input = modal_container.locator('input[type="file"]').first
    if file_input.count() > 0:
        try:
            file_input.set_input_files(cv_pdf)
            print(f"  [TopCV] Attached CV PDF: {os.path.basename(cv_pdf)}")
            time.sleep(2)
        except Exception as fe:
            print(f"  [TopCV] File input attachment failed: {fe}")

    # Fill phone / intro if present
    personal = applicant_profile.get("personal", {})
    phone_input = modal_container.locator('input[name="phone"], input#phone, input[placeholder*="Điện thoại"], input[placeholder*="Phone"]').first
    if phone_input.count() > 0 and personal.get("phone"):
        try:
            phone_input.fill(personal.get("phone"))
        except Exception:
            pass

    # Submission click
    submit_btn = modal_container.locator('button:has-text("Nộp hồ sơ"), button:has-text("Nộp CV"), button:has-text("Gửi hồ sơ"), button#btn-apply-job, button[type="submit"]').first
    proof_path = os.path.join(dirs["proof_dir"], f"{safe_filename(job['company'])}__{job['id']}.png")

    if dry_run:
        print(f"  [TopCV DRY RUN] Capturing dry-run proof before submit: {proof_path}")
        page.screenshot(path=proof_path)
        job["proof_path"] = proof_path
        job["apply_status"] = "Success (Dry Run)"
        return

    if submit_btn.count() > 0 and submit_btn.is_visible():
        print("  [TopCV] Clicking submit button ('Nộp hồ sơ')...")
        submit_btn.click()
        time.sleep(4)
        page.screenshot(path=proof_path)
        job["proof_path"] = proof_path
        job["apply_status"] = "Success (Submitted)"
        print(f"  [TopCV SUCCESS] Submitted TopCV application for {job['title']} at {job['company']}!")
    else:
        print("  [TopCV] Submit button not found in modal. Falling back to agentic apply...")
        _agentic_external_apply(page, job, dirs, cv_file, tailored_cvs, applicant_profile, cv_text, profile_path, dry_run)


def _apply_itviec(page, job, dirs, cv_file, tailored_cvs, applicant_profile, cv_text, profile_path, dry_run):
    """Dedicated native modal application handler for ITviec."""
    print(f"  [ITviec Native Apply] Starting application for {job['title']} at {job['company']}...")
    cv_pdf = tailored_cvs.get(job["id"], cv_file) if tailored_cvs else cv_file

    # 1. Check already applied
    if check_already_applied(page, job, dirs):
        return

    # 2. Check closed
    if check_job_closed(page, job, dirs):
        return

    # 3. Locate apply button
    apply_btn = None
    apply_selectors = [
        'button:has-text("Nộp đơn ứng tuyển")',
        'a:has-text("Nộp đơn ứng tuyển")',
        'button:has-text("Ứng tuyển ngay")',
        'a:has-text("Ứng tuyển ngay")',
        'button:has-text("Apply now")',
        'a:has-text("Apply now")',
        '[data-target="#apply-modal"]',
        '.apply-button',
    ]
    for sel in apply_selectors:
        candidates = page.locator(sel)
        for i in range(candidates.count()):
            c = candidates.nth(i)
            if c.is_visible() and c.is_enabled():
                apply_btn = c
                break
        if apply_btn:
            break

    if not apply_btn:
        print("  [ITviec] No apply button found. Falling back to agentic apply...")
        _agentic_external_apply(page, job, dirs, cv_file, tailored_cvs, applicant_profile, cv_text, profile_path, dry_run)
        return

    print("  [ITviec] Found apply button. Clicking to open application modal...")
    try:
        apply_btn.click()
        time.sleep(3)
    except Exception as ce:
        print(f"  [ITviec] Click apply button failed: {ce}")

    modal_container = page.locator('#apply-modal, .apply-modal, [data-controller*="apply"], form.apply-form')
    if modal_container.count() == 0:
        modal_container = page

    # Check file upload input
    file_input = modal_container.locator('input[type="file"]').first
    if file_input.count() > 0:
        try:
            file_input.set_input_files(cv_pdf)
            print(f"  [ITviec] Attached CV PDF: {os.path.basename(cv_pdf)}")
            time.sleep(2)
        except Exception as fe:
            print(f"  [ITviec] File input attachment failed: {fe}")

    proof_path = os.path.join(dirs["proof_dir"], f"{safe_filename(job['company'])}__{job['id']}.png")
    if dry_run:
        print(f"  [ITviec DRY RUN] Capturing dry-run proof before submit: {proof_path}")
        page.screenshot(path=proof_path)
        job["proof_path"] = proof_path
        job["apply_status"] = "Success (Dry Run)"
        return

    submit_btn = modal_container.locator('button:has-text("Nộp đơn"), button:has-text("Gửi hồ sơ"), button:has-text("Submit application"), button[type="submit"]').first
    if submit_btn.count() > 0 and submit_btn.is_visible():
        print("  [ITviec] Clicking submit button ('Nộp đơn')...")
        try:
            submit_btn.scroll_into_view_if_needed(timeout=3000)
            submit_btn.click(timeout=5000)
        except Exception:
            try:
                submit_btn.click(force=True, timeout=5000)
            except Exception:
                page.evaluate("el => el.click()", submit_btn.element_handle())
        time.sleep(4)
        page.screenshot(path=proof_path)
        job["proof_path"] = proof_path
        job["apply_status"] = "Success (Submitted)"
        print(f"  [ITviec SUCCESS] Submitted ITviec application for {job['title']} at {job['company']}!")
    else:
        print("  [ITviec] Submit button not found in modal. Falling back to agentic apply...")
        _agentic_external_apply(page, job, dirs, cv_file, tailored_cvs, applicant_profile, cv_text, profile_path, dry_run)


def _apply_vietnamworks(page, job, dirs, cv_file, tailored_cvs, applicant_profile, cv_text, profile_path, dry_run):
    """Dedicated native modal application handler for VietnamWorks."""
    print(f"  [VietnamWorks Native Apply] Starting application for {job['title']} at {job['company']}...")
    cv_pdf = tailored_cvs.get(job["id"], cv_file) if tailored_cvs else cv_file

    # 1. Check already applied
    if check_already_applied(page, job, dirs):
        return

    # 2. Check closed
    if check_job_closed(page, job, dirs):
        return

    # 3. Locate apply button
    apply_btn = None
    apply_selectors = [
        'button:has-text("Nộp đơn ứng tuyển")',
        'a:has-text("Nộp đơn ứng tuyển")',
        'button:has-text("Nộp đơn")',
        'a:has-text("Nộp đơn")',
        'button:has-text("Ứng tuyển ngay")',
        'a:has-text("Ứng tuyển ngay")',
        'button:has-text("Apply Now")',
        'a:has-text("Apply Now")',
        'button:has-text("Apply")',
        'a:has-text("Apply")',
        '.btn-apply',
        '#btn-apply-job',
    ]
    for sel in apply_selectors:
        candidates = page.locator(sel)
        for i in range(candidates.count()):
            c = candidates.nth(i)
            if c.is_visible() and c.is_enabled():
                apply_btn = c
                break
        if apply_btn:
            break

    if not apply_btn:
        print("  [VietnamWorks] No apply button found. Falling back to agentic apply...")
        _agentic_external_apply(page, job, dirs, cv_file, tailored_cvs, applicant_profile, cv_text, profile_path, dry_run)
        return

    print("  [VietnamWorks] Found apply button. Clicking to open application modal...")
    try:
        apply_btn.scroll_into_view_if_needed(timeout=3000)
        apply_btn.click()
        time.sleep(3)
    except Exception as ce:
        print(f"  [VietnamWorks] Click apply button failed: {ce}")
        try:
            apply_btn.click(force=True)
            time.sleep(3)
        except Exception:
            pass

    # Locate modal
    modal_container = page.locator('.modal-content, [role="dialog"], .apply-modal, #modal-apply, form[class*="apply"]')
    if modal_container.count() == 0:
        modal_container = page

    # Check file upload input
    file_input = modal_container.locator('input[type="file"]').first
    if file_input.count() > 0:
        try:
            file_input.set_input_files(cv_pdf)
            print(f"  [VietnamWorks] Attached CV PDF: {os.path.basename(cv_pdf)}")
            time.sleep(2)
        except Exception as fe:
            print(f"  [VietnamWorks] File input attachment failed: {fe}")

    proof_path = os.path.join(dirs["proof_dir"], f"{safe_filename(job['company'])}__{job['id']}.png")
    if dry_run:
        print(f"  [VietnamWorks DRY RUN] Capturing dry-run proof before submit: {proof_path}")
        page.screenshot(path=proof_path)
        job["proof_path"] = proof_path
        job["apply_status"] = "Success (Dry Run)"
        return

    submit_btn = modal_container.locator('button:has-text("Nộp đơn"), button:has-text("Gửi hồ sơ"), button:has-text("Hoàn thành ứng tuyển"), button:has-text("Hoàn tất"), button:has-text("Submit"), button[type="submit"]').first
    if submit_btn.count() > 0 and submit_btn.is_visible():
        print("  [VietnamWorks] Clicking submit button...")
        try:
            submit_btn.scroll_into_view_if_needed(timeout=3000)
            submit_btn.click(timeout=5000)
        except Exception:
            try:
                submit_btn.click(force=True, timeout=5000)
            except Exception:
                page.evaluate("el => el.click()", submit_btn.element_handle())
        time.sleep(4)
        page.screenshot(path=proof_path)
        job["proof_path"] = proof_path
        job["apply_status"] = "Success (Submitted)"
        print(f"  [VietnamWorks SUCCESS] Submitted application for {job['title']} at {job['company']}!")
    else:
        print("  [VietnamWorks] Submit button not found in modal. Falling back to agentic apply...")
        _agentic_external_apply(page, job, dirs, cv_file, tailored_cvs, applicant_profile, cv_text, profile_path, dry_run)


def _apply_to_job(
    job,
    cv_file,
    dirs,
    tailored_cvs,
    state_file,
    dry_run,
    browser,
    applicant_profile,
    cv_text,
    profile_path,
):
    """Executes the Playwright flow to apply for a single job."""
    job["apply_status"] = "Failed"  # default
    context_opts = {
        "ignore_https_errors": True,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "locale": "en-US",
        "timezone_id": "Asia/Ho_Chi_Minh",
        "viewport": {"width": 1280, "height": 800},
    }
    if state_file and os.path.exists(state_file):
        context = browser.new_context(storage_state=state_file, **context_opts)
    else:
        context = browser.new_context(**context_opts)
    page = context.new_page()
    from playwright_stealth import Stealth

    Stealth().apply_stealth_sync(page)

    source = job.get("source", "linkedin").lower()

    try:
        import urllib.parse

        if source == "linkedin" or source.startswith("linkedin-"):
            job_url = job.get("url")
            if not job_url:
                search_query = urllib.parse.quote(f"{job['title']} {job['company']}")
                job_url = (
                    f"https://www.linkedin.com/jobs/search/?keywords={search_query}"
                )
            for attempt in range(3):
                try:
                    print(
                        f"  Navigating directly to LinkedIn job URL (attempt {attempt + 1}/3): {job_url}"
                    )
                    page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
                    break
                except Exception as goto_exc:
                    if attempt == 2:
                        raise goto_exc
                    print(
                        f"  [WARNING] Navigating to job URL failed: {goto_exc}. Retrying after 3s..."
                    )
                    time.sleep(3)
            time.sleep(5)

            # Dismiss any open dropdowns/overlays (e.g. search suggestions)
            try:
                page.keyboard.press("Escape")
                time.sleep(1)
            except:
                pass

            # 1. Early detection: Check if already applied
            if check_already_applied(page, job, dirs):
                return

            # 2. Early detection: Check if closed
            if check_job_closed(page, job, dirs):
                return

            # Search for apply button
            apply_btn = None
            try:
                easy_apply_selectors = [
                    ".jobs-apply-button",
                    "button.jobs-apply-button",
                    'button[aria-label*="Easy Apply"]',
                    'button[aria-label*="dễ dàng"]',
                    'button:has-text("Easy Apply")',
                    'button:has-text("easy apply")',
                    'button:has-text("Ứng tuyển dễ dàng")',
                    'button:has-text("Nộp đơn dễ dàng")',
                    '.jobs-s-apply button',
                ]
                generic_apply_selectors = [
                    'button:has-text("Apply")',
                    'button:has-text("Ứng tuyển")',
                    'button:has-text("Nộp đơn")',
                    'a:has-text("Easy Apply")',
                    'a:has-text("Apply")',
                    'a:has-text("Ứng tuyển")',
                    'a:has-text("Nộp đơn")',
                    ".jobs-s-apply",
                ]

                # Poll for up to 25 seconds page-wide for any visible and enabled apply button
                print(
                    "  [DEBUG] Polling page-wide for visible and enabled apply button..."
                )
                for poll_step in range(25):
                    # Check dedicated easy apply buttons first
                    for sel in easy_apply_selectors:
                        candidates = page.locator(sel)
                        for idx in range(candidates.count()):
                            c = candidates.nth(idx)
                            try:
                                if c.is_visible() and c.is_enabled():
                                    apply_btn = c
                                    break
                            except:
                                pass
                        if apply_btn is not None:
                            break
                    if apply_btn is not None:
                        break

                    # Fallback to generic selectors if not found yet
                    for sel in generic_apply_selectors:
                        candidates = page.locator(sel)
                        for idx in range(candidates.count()):
                            c = candidates.nth(idx)
                            try:
                                if c.is_visible() and c.is_enabled():
                                    apply_btn = c
                                    break
                            except:
                                pass
                        if apply_btn is not None:
                            break
                    if apply_btn is not None:
                        break
                    time.sleep(1)
            except Exception as e:
                print(f"  [DEBUG] Direct apply button locator failed: {e}", flush=True)

            # If we successfully found the apply button, proceed with application
            if apply_btn is not None:
                try:
                    btn_text = apply_btn.inner_text().strip().lower()

                    # Robust language-agnostic check for Easy Apply
                    is_easy_apply = any(
                        kw in btn_text
                        for kw in ["easy apply", "dễ dàng", "easy", "hồ sơ trực tuyến"]
                    ) or any(
                        cls in (apply_btn.get_attribute("class") or "")
                        for cls in ["jobs-apply-button", "jobs-s-apply"]
                    )

                    if is_easy_apply:
                        href = apply_btn.get_attribute("href") or ""
                        if "/apply/" in href:
                            print(f"  [DEBUG] Navigating directly to Easy Apply URL: {href}")
                            page.goto(href, wait_until="domcontentloaded", timeout=45000)
                            time.sleep(3)
                            try:
                                page.wait_for_selector('.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]', timeout=12000)
                            except Exception:
                                pass
                        else:
                            try:
                                apply_btn.scroll_into_view_if_needed(timeout=3000)
                            except Exception:
                                pass
                            try:
                                apply_btn.click(timeout=5000)
                            except Exception:
                                try:
                                    apply_btn.click(force=True, timeout=5000)
                                except Exception:
                                    page.evaluate("el => el.click()", apply_btn.element_handle())
                            time.sleep(2)

                        share_btn = page.locator(
                            'button[aria-label*="Continue to apply"], button:has-text("Continue applying"), [aria-label="Continue applying"]'
                        )
                        if share_btn.count() > 0 and share_btn.first.is_visible():
                            share_btn.first.click()
                            time.sleep(2)
                        _fill_easy_apply_modal(
                            page,
                            job,
                            cv_file,
                            dirs,
                            tailored_cvs,
                            applicant_profile,
                            cv_text,
                            profile_path,
                            dry_run,
                        )
                    else:
                        _handle_external_apply(
                            page,
                            context,
                            job,
                            dirs,
                            btn_text,
                            applicant_profile,
                            cv_text,
                            profile_path,
                            tailored_cvs,
                            cv_file,
                            dry_run,
                            apply_btn,
                        )
                except Exception as apply_err:
                    print(f"  [ERROR] Apply interaction failed: {apply_err}")
                    job["apply_status"] = "Failed"
            else:
                # No apply button found! Determine if it is already applied, closed, or a bug.
                print(
                    "  [DEBUG] No apply button found. Running fallback verification...",
                    flush=True,
                )

                # Check for already applied status again
                if check_already_applied(page, job, dirs):
                    return

                # Check for closed status again
                if check_job_closed(page, job, dirs):
                    return

                # If it's neither applied nor closed, it's a bug!
                print(
                    f"  [BUG] Missing apply button on active open job: {job['title']} at {job['company']}"
                )
                job["apply_status"] = "Failed (Apply Button Not Found)"
                proof_file = os.path.join(
                    dirs["proof_dir"],
                    f"bug_no_apply_{safe_filename(job['company'])}__{job['id']}.png",
                )
                try:
                    page.screenshot(path=proof_file)
                    job["proof_path"] = proof_file
                    print(
                        f"  [SCREENSHOT] Captured bug no apply screenshot: {proof_file}"
                    )
                except Exception as se:
                    print(f"  [WARNING] Failed to capture bug screenshot: {se}")

        elif source == "topcv":
            print(f"  Navigating to TopCV job URL: {job['url']}")
            page.goto(job["url"], wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            _apply_topcv(
                page,
                job,
                dirs,
                cv_file,
                tailored_cvs,
                applicant_profile,
                cv_text,
                profile_path,
                dry_run,
            )

        elif source == "itviec":
            print(f"  Navigating to ITviec job URL: {job['url']}")
            page.goto(job["url"], wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            _apply_itviec(
                page,
                job,
                dirs,
                cv_file,
                tailored_cvs,
                applicant_profile,
                cv_text,
                profile_path,
                dry_run,
            )

        elif source == "vietnamworks":
            print(f"  Navigating to VietnamWorks job URL: {job['url']}")
            page.goto(job["url"], wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            _apply_vietnamworks(
                page,
                job,
                dirs,
                cv_file,
                tailored_cvs,
                applicant_profile,
                cv_text,
                profile_path,
                dry_run,
            )

        else:
            # Generic approach for other sources (Careerjet, Indeed, Glints)
            print(
                f"  Navigating directly to job URL for source '{source}': {job['url']}"
            )
            page.goto(job["url"], wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

            # Delegate to agentic web agent for the apply flow
            _agentic_external_apply(
                page,
                job,
                dirs,
                cv_file,
                tailored_cvs,
                applicant_profile,
                cv_text,
                profile_path,
                dry_run,
            )


        status = job.get("apply_status", "")
        if "Manual" in status or "Stuck" in status:
            monitor_page = page
            if context.pages:
                monitor_page = context.pages[-1]

            if os.environ.get("JOBHUNTER_ALLOW_MANUAL") == "1":
                print(
                    f"\n  [MANUAL INTERVENTION] Waiting for manual completion of {job['title']} at {job['company']}..."
                )
                print(
                    "  [MANUAL INTERVENTION] Please fill out any remaining fields and submit. The script will monitor the page for 5 minutes."
                )
                timeout_limit = 300
                monitor_manual_submission(monitor_page, job, dirs, timeout_limit)
            else:
                print("  [UNATTENDED MODE] Logged manual/stuck state. Proceeding without 5m delay...")

    except Exception as e:
        print(f"  [ERROR] Failed to apply: {e}")
    finally:
        context.close()


def _load_applicant_profile_and_cv(cv_file):
    """Loads applicant profile and extracts CV text."""
    profile_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "applicant_profile.json",
    )
    try:
        with open(profile_path, encoding="utf-8") as f:
            applicant_profile = json.load(f)
    except Exception as e:
        print(f"  [WARNING] Could not load applicant_profile.json: {e}")
        applicant_profile = {}

    cv_text = ""
    if cv_file:
        try:
            if cv_file.lower().endswith(".pdf"):
                import fitz

                doc = fitz.open(cv_file)
                cv_text = "".join(page.get_text() for page in doc)
                doc.close()
            else:
                with open(cv_file, encoding="utf-8") as f:
                    cv_text = f.read()
        except Exception as e:
            print(f"  [WARNING] Could not extract CV text: {e}")

    return applicant_profile, cv_text, profile_path


def auto_apply(
    passed_jobs,
    cv_file,
    dirs,
    tailored_cvs=None,
    state_file=None,
    dry_run=False,
    cli_mode: bool = False,
):
    """Automates the LinkedIn Easy Apply process using playwright-stealth. (UC-005)"""
    print("[UTOP|func|auto_apply|cp-fr-013]")
    print(
        f"[Phase 4: Auto-Apply] Initiating automated application process... (Dry Run: {dry_run})"
    )

    profile, cv_text, profile_path = _load_applicant_profile_and_cv(cv_file)
    already_submitted = set()
    already_submitted_companies = set()
    already_submitted_urls = set()
    if cli_mode:
        _, already_submitted, already_submitted_companies, already_submitted_urls = (
            _load_applied_history(dirs["history_file"], dry_run)
        )

    if not PLAYWRIGHT_AVAILABLE:
        print("  [WARNING] Playwright not installed. Cannot apply.")
        return

    import threading
    from concurrent.futures import ThreadPoolExecutor

    global profile_lock
    if "profile_lock" not in globals():
        profile_lock = threading.Lock()

    # Filter out jobs that are already applied
    jobs_to_process = []
    for job in passed_jobs:
        job_key = f"{job['title'].strip()} @ {job['company'].strip()}".lower()
        job_url = job.get("url")
        clean_url = job_url.split("?")[0].strip().lower() if job_url else ""
        if job_key in already_submitted or (
            clean_url and clean_url in already_submitted_urls
        ):
            print(
                f"  [SKIP] Already submitted/processed this job previously: {job['title']} at {job['company']}"
            )
            job["apply_status"] = "Skipped (Already Applied)"
            continue
        jobs_to_process.append(job)

    if not jobs_to_process:
        print("  No new jobs to apply to.")
        if cli_mode:
            _save_applied_history(
                dirs["history_file"], passed_jobs, tailored_cvs, cv_file, dirs
            )
        return

    def apply_worker(job):
        print(f"\n  [Applying - Thread] {job['title']} at {job['company']}")
        with sync_playwright() as p:
            headless = os.environ.get("JOBHUNTER_HEADLESS", "true").lower() not in (
                "false",
                "0",
            )
            browser = p.chromium.launch(
                headless=headless,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-position=0,0",
                ],
            )
            try:
                _apply_to_job(
                    job,
                    cv_file,
                    dirs,
                    tailored_cvs,
                    state_file,
                    dry_run,
                    browser,
                    profile,
                    cv_text,
                    profile_path,
                )
            except Exception as e:
                print(f"  [ERROR] Thread failed for {job['company']}: {e}")
                job["apply_status"] = "Failed"
            finally:
                browser.close()

    print(
        f"  Processing {len(jobs_to_process)} job applications in parallel (max 3 workers)..."
    )
    with ThreadPoolExecutor(max_workers=3) as executor:
        executor.map(apply_worker, jobs_to_process)

    if cli_mode:
        _save_applied_history(
            dirs["history_file"], passed_jobs, tailored_cvs, cv_file, dirs
        )
    print("[Phase 4: Auto-Apply] All applications processed.\n")


def verify_submission_proof(page, job, proof_dir, max_wait_sec=5) -> bool:
    """Verifies application submission by checking page content or locator text and saving proof screenshot."""
    os.makedirs(proof_dir, exist_ok=True)
    curr_url = getattr(page, "url", "")
    content = ""
    try:
        if hasattr(page, "locator"):
            loc = page.locator("body")
            try:
                content = loc.inner_text()
            except Exception:
                pass
        if not content and hasattr(page, "content"):
            content = page.content()
    except Exception:
        pass

    from core.apply_mechanics import check_submission_confirmation, safe_filename

    is_confirmed = check_submission_confirmation(curr_url, content)

    if is_confirmed:
        job_id = job.get("id", "unknown")
        company = safe_filename(job.get("company", "Company"))
        proof_path = os.path.join(proof_dir, f"proof_submitted_{company}_{job_id}.png")
        try:
            if hasattr(page, "screenshot"):
                page.screenshot(path=proof_path)
                job["proof_path"] = proof_path
        except Exception:
            pass
        job["apply_status"] = "Success (Submitted)"
        return True

    return False
