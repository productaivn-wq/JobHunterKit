"""
ipc_utils.py — Inter-Process Communication & DOM Utility helpers for JobHunterKit.

Provides cross-process file locks, DOM element parsing, selector resolution,
and accent normalization for browser automation.
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

IPC_DIR = Path(__file__).resolve().parent.parent / "ipc"
ipc_lock = threading.Lock()
ready_count = 0
ready_lock = threading.Lock()


def acquire_cross_process_lock(lock_file: Path, timeout: float = 300.0) -> bool:
    """Acquires an atomic cross-process filesystem lock, handling stale lock file cleanup."""
    if os.environ.get("BYPASS_LOCK") == "1":
        return True
    start_time = time.time()
    while True:
        try:
            # Atomic creation of the lock file
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(f"{os.getpid()}\n{time.time()}")
            return True
        except FileExistsError:
            try:
                if lock_file.exists():
                    stat = lock_file.stat()
                    if time.time() - stat.st_mtime > 180.0:
                        print(
                            f"[IPC] Stale lock detected, clearing {lock_file.name}",
                            flush=True,
                        )
                        lock_file.unlink(missing_ok=True)
                        continue
            except Exception as stat_err:
                print(f"[IPC DEBUG] Lock stat failed: {stat_err}", flush=True)
            if time.time() - start_time > timeout:
                raise TimeoutError(
                    f"Failed to acquire cross-process lock on {lock_file} after {timeout} seconds."
                )
            time.sleep(0.5)


def release_cross_process_lock(lock_file: Path) -> None:
    """Releases a previously acquired filesystem lock."""
    if os.environ.get("BYPASS_LOCK") == "1":
        return
    try:
        lock_file.unlink(missing_ok=True)
    except Exception as e:
        print(f"[IPC] Error releasing lock: {e}", flush=True)


def parse_dom_elements(prompt_text: str) -> list[dict[str, Any]]:
    """Extracts JSON DOM element definitions from an agent prompt string."""
    try:
        idx = prompt_text.find("DOM Elements:")
        if idx == -1:
            idx = prompt_text.find("Elements:")
        if idx != -1:
            dom_sec = prompt_text[idx:]
            start = dom_sec.find("[")
            if start != -1:
                bracket_count = 0
                end = -1
                for i in range(start, len(dom_sec)):
                    if dom_sec[i] == "[":
                        bracket_count += 1
                    elif dom_sec[i] == "]":
                        bracket_count -= 1
                        if bracket_count == 0:
                            end = i
                            break
                if end != -1:
                    return json.loads(dom_sec[start : end + 1])
    except Exception as e:
        print(f"[IPC WARNING] Error parsing DOM elements: {e}", flush=True)
    return []


def get_selector(el: dict[str, Any]) -> str:
    """Computes a robust Playwright selector for a parsed DOM element."""
    override = el.get("selector_override")
    if override:
        return override
    tag = str(el.get("tag", "")).upper()
    el_id = el.get("id")
    if el_id:
        if el_id[0].isdigit():
            return f"[id='{el_id}']"
        return f"#{el_id}"

    el_name = el.get("name")
    if el_name:
        return f"{tag.lower()}[name='{el_name}']"

    placeholder = el.get("placeholder", "").strip()
    if tag == "INPUT" and placeholder:
        escaped_placeholder = placeholder.replace("'", "'")
        return f"input[placeholder='{escaped_placeholder}']"

    aria = el.get("aria_label", "").strip()
    if aria:
        escaped_aria = aria.replace("'", "'")
        if tag == "INPUT":
            return f"input[aria-label='{escaped_aria}']"
        return f"{tag.lower()}[aria-label='{escaped_aria}']"

    text = el.get("text", "").strip()
    if tag == "INPUT":
        el_type = el.get("type", "").lower()
        if el_type in ("radio", "checkbox"):
            if text:
                return f"input[value='{text}']"
        return ""

    if text:
        escaped_text = text.replace('"', '"')
        return f'{tag.lower()}:has-text("{escaped_text}")'

    return ""


def strip_vietnamese_accents(s: str) -> str:
    """Normalizes Vietnamese text to unaccented lowercase ASCII representation."""
    import unicodedata

    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


def is_cv_already_selected(elements: list[dict[str, Any]], prompt_clean: str) -> bool:
    """Detects if candidate CV is already selected in an interactive form."""
    import re

    # Find CV filename in prompt_clean
    cv_match = re.search(r"tailored\\([^\s]+\.pdf)", prompt_clean, re.I)
    if not cv_match:
        cv_match = re.search(r"tailored/([^\s]+\.pdf)", prompt_clean, re.I)
    if not cv_match:
        return False

    cv_filename = cv_match.group(1).lower()
    # Extract significant parts of the filename (e.g. alphanumeric words of length >= 4)
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", cv_filename)
        if len(w) >= 4 and w not in ("vietnamworks", "limited", "company", "tailored")
    ]
    if not words:
        return False

    # Check if there is any radio or checkbox that is checked and contains at least one of these words in its text
    for el in elements:
        tag = str(el.get("tag", "")).lower()
        el_type = str(el.get("type", "")).lower()
        checked = el.get("checked", False)
        if checked and tag == "input" and el_type in ("radio", "checkbox"):
            text_clean = strip_vietnamese_accents(str(el.get("text", "")))
            if any(w in text_clean for w in words):
                return True
    return False


def decode_unicode_escapes(prompt_text: str) -> str:
    """Safely decodes unicode escape sequences in raw prompt strings."""
    # Safe regex-based decode of any JSON-escaped unicode sequences (\\uXXXX)
    import re

    def decode_match(match):
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    try:
        return re.sub(r"\\u([0-9a-fA-F]{4})", decode_match, prompt_text)
    except Exception as e:
        print(f"[IPC WARNING] Failed to decode unicode escapes: {e}", flush=True)
        return prompt_text


def classify_dom_elements(
    elements: list[dict[str, Any]],
    is_secondary_form_open: bool,
    is_max_cvs_modal: bool,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Categorizes DOM elements into file uploads, text inputs, radios, checkboxes, and selects."""
    upload_input = None
    text_inputs = []
    radios = []
    checkboxes = []
    selects = []

    for el in elements:
        tag = str(el.get("tag", "")).lower()
        text_clean = strip_vietnamese_accents(str(el.get("text", "")))
        aria_clean = strip_vietnamese_accents(str(el.get("aria_label", "")))
        el_type = str(el.get("type", "")).lower()

        if "easy apply" in text_clean or "easy apply" in aria_clean:
            pass
        elif any(
            x in text_clean for x in ("next", "continue", "next step", "proceed")
        ) or any(x in aria_clean for x in ("next", "continue")):
            pass
        elif "review" in text_clean or "review" in aria_clean:
            pass
        elif "submit" in text_clean or "submit" in aria_clean:
            pass
        elif (
            el_type == "file"
            or "upload resume" in text_clean
            or "upload resume" in aria_clean
        ):
            if not is_max_cvs_modal:
                upload_input = el
        elif el_type == "checkbox":
            checkboxes.append(el)
        elif el_type == "radio":
            radios.append(el)
        elif tag == "input":
            if el_type in ("text", "tel", "email", "number") and is_secondary_form_open:
                text_inputs.append(el)
        elif tag == "textarea" and is_secondary_form_open:
            text_inputs.append(el)
        elif tag == "select" and is_secondary_form_open:
            selects.append(el)

    return upload_input, text_inputs, radios, checkboxes, selects


def handle_secondary_form_dropdowns(elements, is_secondary_form_open: bool):
    if not is_secondary_form_open:
        return None

    sub_kws = (
        "dau tu tai chinh",
        "quan ly quy",
        "dich vu ho tro khach hang",
        "phan mem",
        "phan cung",
        "lap trinh",
        "phat trien phan mem",
    )
    cat_kws = (
        "ngan hang",
        "tai chinh",
        "dich vu tai chinh",
        "ban le / ban si",
        "ban le/ban si",
        "ban le / ban si / thuong mai",
        "ban le/ban si/thuong mai",
    )

    # 1. Detect dropdown open states
    is_industry_dropdown_open = False
    is_category_dropdown_open = False
    for el in elements:
        sel = get_selector(el)
        if not sel or not el.get("is_dropdown"):
            continue
        if any(x in sel for x in ("sc-3d832d27", "sc-aff9a10")):
            is_industry_dropdown_open = True
        elif any(x in sel for x in ("sc-3efb7cc9", "sc-bc869e04")):
            is_category_dropdown_open = True

    # 2. Find all dropdown triggers and check their selection state
    industry_triggers = []  # list of (el, is_selected)
    category_triggers = []  # list of (el, is_selected)

    is_second_section_visible = any(
        "mong muon"
        in strip_vietnamese_accents(
            str(el.get("text", "") or el.get("label", "") or "")
        )
        for el in elements
    )

    for el in elements:
        label = strip_vietnamese_accents(
            str(el.get("label", "") or el.get("text", "") or "")
        )
        text_clean = strip_vietnamese_accents(str(el.get("text", "")))
        sel = get_selector(el)
        if not sel:
            continue

        # Check if it's a dropdown trigger
        is_trigger = el.get("tag") == "DIV" and (
            "multiple-select" in sel
            or "data-input-container" in sel
            or any(
                c in sel
                for c in (
                    "eYpDgg",
                    "iWGIIJ",
                    "iWLotl",
                    "jvJfai",
                    "jnZxBX",
                    "jZStDg",
                    "jqFval",
                    "iDlmDJ",
                )
            )
        )
        if is_trigger:
            if "nganh nghe" in label:
                if not is_second_section_visible and "hien tai" not in label:
                    continue
                if "hien tai" in label:
                    is_sel = any(kw in text_clean for kw in sub_kws)
                else:
                    is_sel = not any(
                        ph in text_clean
                        for ph in ("chon nganh nghe", "chon linh vuc", "chon")
                    )
                industry_triggers.append((el, is_sel))
            elif "linh vuc" in label or "linh vuc" in text_clean:
                if not is_second_section_visible and "hien tai" not in label:
                    continue
                if "hien tai" in label:
                    is_sel = any(kw in text_clean for kw in cat_kws)
                else:
                    is_sel = not any(
                        ph in text_clean
                        for ph in ("chon nganh nghe", "chon linh vuc", "chon")
                    )
                category_triggers.append((el, is_sel))

    # 3. Action logic
    # A. Industry dropdown logic
    unselected_ind = [el for el, is_sel in industry_triggers if not is_sel]
    if unselected_ind:
        if is_industry_dropdown_open:
            # Option selection loop supporting subcategory and parent category hierarchy
            parent_kws = (
                "ngan hang",
                "ngan hang / dich vu tai chinh",
                "ngan hang & dich vu tai chinh",
                "cong nghe thong tin",
            )
            subcategory_matches = []
            parent_matches = []
            for el in elements:
                text_clean = strip_vietnamese_accents(str(el.get("text", "")))
                sel = get_selector(el)
                if not sel or not el.get("is_dropdown"):
                    continue
                if text_clean in sub_kws:
                    if "sc-3d832d27" in sel or "sc-aff9a10" in sel:
                        subcategory_matches.append((el, sel))
                elif text_clean in parent_kws:
                    if "sc-aff9a10" not in sel and (
                        "sc-3d832d27" in sel or "sc-aff9a10" in sel
                    ):
                        parent_matches.append((el, sel))

            if subcategory_matches:
                best_el, best_sel = subcategory_matches[0]
                return {
                    "response": {
                        "action": "click",
                        "selector": best_sel,
                        "value": "",
                        "reasoning": f"Selecting Industry subcategory option '{best_el.get('text')}'.",
                    }
                }
            elif parent_matches:
                best_el, best_sel = parent_matches[0]
                return {
                    "response": {
                        "action": "click",
                        "selector": best_sel,
                        "value": "",
                        "reasoning": f"Selecting Industry parent option '{best_el.get('text')}'.",
                    }
                }
        else:
            # Open the first unselected Industry trigger
            sel = get_selector(unselected_ind[0])
            return {
                "response": {
                    "action": "click",
                    "selector": sel,
                    "value": "",
                    "reasoning": "Opening unselected Industry dropdown.",
                }
            }

    # B. Category dropdown logic
    unselected_cat = [el for el, is_sel in category_triggers if not is_sel]
    if unselected_cat:
        if is_category_dropdown_open:
            # Option selection loop
            for el in elements:
                text_clean = strip_vietnamese_accents(str(el.get("text", "")))
                sel = get_selector(el)
                if not sel or not el.get("is_dropdown"):
                    continue
                if text_clean in cat_kws:
                    if "sc-3efb7cc9" in sel or "sc-bc869e04" in sel:
                        if not el.get("checked", False):
                            return {
                                "response": {
                                    "action": "click",
                                    "selector": sel,
                                    "value": "",
                                    "reasoning": f"Selecting Category option '{el.get('text')}'.",
                                }
                            }
        else:
            # Open the first unselected Category trigger
            sel = get_selector(unselected_cat[0])
            return {
                "response": {
                    "action": "click",
                    "selector": sel,
                    "value": "",
                    "reasoning": "Opening unselected Category dropdown.",
                }
            }
    elif is_category_dropdown_open:
        # Close it if all category fields are selected
        if category_triggers:
            sel = get_selector(category_triggers[0][0])
            return {
                "response": {
                    "action": "click",
                    "selector": sel,
                    "value": "",
                    "reasoning": "Closing Category dropdown since all fields are selected.",
                }
            }

    return None


def handle_radios(
    elements,
    radios,
    is_max_cvs_modal: bool,
    is_visa_question: bool,
    is_auth_question: bool,
):
    if not radios:
        return None

    # If max CVs modal is open, filter to only the cv-file radios inside the modal
    if is_max_cvs_modal:
        radios = [
            r
            for r in radios
            if "cv-file" in str(r.get("name")).lower()
            or "cv-file" in str(r.get("text")).lower()
        ]

    any_checked = any(rd.get("checked") for rd in radios)
    if not any_checked and radios:
        for rd in radios:
            label = strip_vietnamese_accents(
                str(rd.get("text", "") or rd.get("aria_label", ""))
            )
            sel = get_selector(rd)
            if not sel:
                continue
            if is_visa_question:
                if "no" in label or "khong" in label:
                    return {
                        "response": {
                            "action": "click",
                            "selector": sel,
                            "value": "",
                            "reasoning": "Answering No to visa sponsorship question.",
                        }
                    }
            elif is_auth_question:
                if "yes" in label or "co" in label:
                    return {
                        "response": {
                            "action": "click",
                            "selector": sel,
                            "value": "",
                            "reasoning": "Answering Yes to work authorization question.",
                        }
                    }
            else:
                if "yes" in label or "co" in label:
                    return {
                        "response": {
                            "action": "click",
                            "selector": sel,
                            "value": "",
                            "reasoning": "Answering Yes by default.",
                        }
                    }

        sel = get_selector(radios[0])
        if sel:
            return {
                "response": {
                    "action": "click",
                    "selector": sel,
                    "value": "",
                    "reasoning": "Clicking first radio option.",
                }
            }
    elif any_checked and is_max_cvs_modal:
        # If one of the modal radios is already checked, and the modal is open, click the "Thay thế" button inside the modal to confirm!
        for el in elements:
            tag = str(el.get("tag", "")).lower()
            text_clean = strip_vietnamese_accents(str(el.get("text", "")))
            if tag == "button" and "thay the" in text_clean:
                sel = get_selector(el)
                if sel:
                    return {
                        "response": {
                            "action": "click",
                            "selector": sel,
                            "value": "",
                            "reasoning": "Clicking Thay the to confirm replacement in modal.",
                        }
                    }

    return None


def handle_selects(selects, is_visa_question: bool, is_auth_question: bool):
    for sel_el in selects:
        sel = get_selector(sel_el)
        if not sel:
            continue
        if is_visa_question:
            return {
                "response": {
                    "action": "type",
                    "selector": sel,
                    "value": "No",
                    "reasoning": "Selecting No for visa.",
                }
            }
        elif is_auth_question:
            return {
                "response": {
                    "action": "type",
                    "selector": sel,
                    "value": "Yes",
                    "reasoning": "Selecting Yes for work authorization.",
                }
            }
        else:
            label = strip_vietnamese_accents(
                str(sel_el.get("text", "") or sel_el.get("aria_label", "") or "")
            )
            if "email" in label:
                return {
                    "response": {
                        "action": "type",
                        "selector": sel,
                        "value": "applicant@example.com",
                        "reasoning": "Selecting email option.",
                    }
                }
            elif "country" in label or "code" in label:
                return {
                    "response": {
                        "action": "type",
                        "selector": sel,
                        "value": "Vietnam (+84)",
                        "reasoning": "Selecting country code option.",
                    }
                }
            return {
                "response": {
                    "action": "type",
                    "selector": sel,
                    "value": "Yes",
                    "reasoning": "Selecting Yes/default option.",
                }
            }
    return None


def handle_text_inputs(text_inputs):
    for inp in text_inputs:
        if inp.get("text", "").strip():
            continue
        label = strip_vietnamese_accents(
            str(
                inp.get("label", "")
                or inp.get("text", "")
                or inp.get("aria_label", "")
                or inp.get("placeholder", "")
            )
        )
        sel = get_selector(inp)
        if not sel:
            continue

        if any(x in label for x in ("phone", "mobile", "contact", "sdt", "dien thoai")):
            return {
                "response": {
                    "action": "type",
                    "selector": sel,
                    "value": "+84 90 000 0000",
                    "reasoning": "Filling phone number.",
                }
            }
        elif "email" in label:
            return {
                "response": {
                    "action": "type",
                    "selector": sel,
                    "value": "applicant@example.com",
                    "reasoning": "Filling email.",
                }
            }
        elif any(x in label for x in ("experience", "years", "nam", "kinh nghiem")):
            return {
                "response": {
                    "action": "type",
                    "selector": sel,
                    "value": "5",
                    "reasoning": "Filling experience years.",
                }
            }
        elif any(x in label for x in ("birth", "ngay sinh")):
            return {
                "response": {
                    "action": "type",
                    "selector": sel,
                    "value": "04/01/1986",
                    "reasoning": "Filling date of birth.",
                }
            }
        elif any(x in label for x in ("address", "dia chi")):
            return {
                "response": {
                    "action": "type",
                    "selector": sel,
                    "value": "707 Xô Viết Nghệ Tĩnh",
                    "reasoning": "Filling address.",
                }
            }
        elif any(x in label for x in ("salary", "luong")):
            return {
                "response": {
                    "action": "type",
                    "selector": sel,
                    "value": "2000",
                    "reasoning": "Filling salary.",
                }
            }
        elif any(x in label for x in ("title", "chuc danh", "position", "vi tri")):
            return {
                "response": {
                    "action": "type",
                    "selector": sel,
                    "value": "Product Owner",
                    "reasoning": "Filling job title.",
                }
            }
        else:
            if "city" in label or "location" in label or "thanh pho" in label:
                return {
                    "response": {
                        "action": "type",
                        "selector": sel,
                        "value": "Ho Chi Minh City",
                        "reasoning": "Filling city.",
                    }
                }
            elif "state" in label or "province" in label:
                return {
                    "response": {
                        "action": "type",
                        "selector": sel,
                        "value": "Ho Chi Minh",
                        "reasoning": "Filling state.",
                    }
                }
            elif "first name" in label or "given name" in label or label == "ten":
                return {
                    "response": {
                        "action": "type",
                        "selector": sel,
                        "value": "Applicant",
                        "reasoning": "Filling first name.",
                    }
                }
            elif "last name" in label or "family name" in label or label == "ho":
                return {
                    "response": {
                        "action": "type",
                        "selector": sel,
                        "value": "Vo",
                        "reasoning": "Filling last name.",
                    }
                }
            else:
                return {
                    "response": {
                        "action": "type",
                        "selector": sel,
                        "value": "5",
                        "reasoning": "Filling default numeric value.",
                    }
                }
    return None


def handle_checkboxes(checkboxes):
    for cb in checkboxes:
        if not cb.get("checked"):
            sel = get_selector(cb)
            if sel:
                return {
                    "response": {
                        "action": "click",
                        "selector": sel,
                        "value": "",
                        "reasoning": "Checking checkbox.",
                    }
                }
    return None


def handle_cookie_consent(elements):
    for el in elements:
        if el.get("type") == "checkbox":
            continue
        text_clean = strip_vietnamese_accents(str(el.get("text", "")))
        aria_clean = strip_vietnamese_accents(str(el.get("aria_label", "")))
        sel = get_selector(el)
        if not sel:
            continue
        if any(
            x in text_clean or x in aria_clean
            for x in (
                "accept cookie",
                "allow all",
                "accept all",
                "allow cookies",
                "chap nhan cookie",
            )
        ):
            return {
                "response": {
                    "action": "click",
                    "selector": sel,
                    "value": "",
                    "reasoning": "Dismissing cookie consent banner.",
                }
            }
        if any(x in text_clean or x in aria_clean for x in ("agree", "dong y")):
            if text_clean in (
                "dong y",
                "dong y tat ca",
                "dong y & tiep tuc",
                "dong y va tiep tuc",
                "toi dong y",
            ) or (
                "agree" in text_clean
                and len(text_clean) < 15
                and not any(y in text_clean for y in ("with", "to", "policy", "terms"))
            ):
                return {
                    "response": {
                        "action": "click",
                        "selector": sel,
                        "value": "",
                        "reasoning": "Dismissing cookie consent banner.",
                    }
                }
    return None


def handle_autofill_and_buttons(elements):
    # Look for Autofill with Resume
    for el in elements:
        text_clean = strip_vietnamese_accents(str(el.get("text", "")))
        sel = get_selector(el)
        if not sel:
            continue
        if "autofill" in text_clean:
            return {
                "response": {
                    "action": "click",
                    "selector": sel,
                    "value": "",
                    "reasoning": "Clicking autofill with resume.",
                }
            }

    # Prioritize Autofill / Next / Continue / Submit / Proceed / Progress / Replace buttons (excluding "thay the" here as it is handled explicitly for max CVs modal)
    progress_kws = (
        "next",
        "continue",
        "submit",
        "save",
        "tiep tuc",
        "nop don ngay",
        "apply now",
        "autofill",
        "proceed",
        "ung tuyen",
    )
    for el in elements:
        tag = str(el.get("tag", "")).lower()
        text_clean = strip_vietnamese_accents(str(el.get("text", ""))).strip()
        aria_clean = strip_vietnamese_accents(str(el.get("aria_label", ""))).strip()
        sel = get_selector(el)
        if not sel:
            continue
        if tag in ("button", "a", "div", "span", "input"):
            if any(x in text_clean or x in aria_clean for x in progress_kws):
                return {
                    "response": {
                        "action": "click",
                        "selector": sel,
                        "value": "",
                        "reasoning": f"Clicking progress action button/link '{el.get('text', '')}'.",
                    }
                }

    # Fall back to entry-point buttons (Nộp đơn, Apply, Easy Apply)
    entry_kws = ("nop don", "apply", "easy apply")
    for el in elements:
        tag = str(el.get("tag", "")).lower()
        text_clean = strip_vietnamese_accents(str(el.get("text", ""))).strip()
        aria_clean = strip_vietnamese_accents(str(el.get("aria_label", ""))).strip()
        sel = get_selector(el)
        if not sel:
            continue
        if tag in ("button", "a", "div", "span", "input"):
            if any(x in text_clean or x in aria_clean for x in entry_kws):
                return {
                    "response": {
                        "action": "click",
                        "selector": sel,
                        "value": "",
                        "reasoning": f"Clicking entry-point action button/link '{el.get('text', '')}'.",
                    }
                }

    # Fallback to Next
    return {
        "response": {
            "action": "click",
            "selector": '[role="dialog"] button:has-text("Next"), div.jobs-easy-apply-modal button:has-text("Next")',
            "value": "",
            "reasoning": "Clicking fallback Next button.",
        }
    }


def get_visual_agent_response(prompt_text, req_id):
    prompt_text = decode_unicode_escapes(prompt_text)

    prompt_lower = prompt_text.lower()
    prompt_clean = strip_vietnamese_accents(prompt_lower)

    import re

    url_match = re.search(r"current page url:\s*([^\s]+)", prompt_clean)
    if url_match:
        current_url = url_match.group(1)
        is_vietnamworks = "vietnamworks.com" in current_url
        is_linkedin = "linkedin.com" in current_url
    else:
        is_vietnamworks = "vietnamworks" in prompt_clean
        is_linkedin = (
            "linkedin.com/jobs" in prompt_clean
            or "linkedin.com/checkpoint" in prompt_clean
        )

    if not (is_vietnamworks or is_linkedin):
        print(
            "[IPC] External site detected. Skipping local rules resolver and delegating to LLM.",
            flush=True,
        )
        return None

    elements = parse_dom_elements(prompt_text)
    if not elements:
        return None

    print(
        f"[IPC] Parsed {len(elements)} DOM elements from request {req_id}", flush=True
    )

    if any(
        k in prompt_clean
        for k in (
            "application submitted",
            "successfully applied",
            "chuc mung",
            "da nop don",
            "nop don thanh cong",
        )
    ):
        return {
            "response": {
                "action": "done",
                "reasoning": "Application confirmation page detected.",
            }
        }

    # Detect maximum uploaded CVs modal (only if the "Thay thế" button is visible and parsed)
    is_max_cvs_modal = False
    is_secondary_form_open = any(
        any(
            k in strip_vietnamese_accents(str(el.get("label", "")))
            for k in ("ngay sinh", "dia chi", "dien thoai")
        )
        for el in elements
    )
    for el in elements:
        tag = str(el.get("tag", "")).lower()
        text_clean = strip_vietnamese_accents(str(el.get("text", "")))
        if tag == "button" and "thay the" in text_clean:
            is_max_cvs_modal = True
            break

    upload_input, text_inputs, radios, checkboxes, selects = classify_dom_elements(
        elements, is_secondary_form_open, is_max_cvs_modal
    )

    # Detect if the tailored CV is already selected
    if upload_input and is_cv_already_selected(elements, prompt_clean):
        print("[IPC] Tailored CV is already selected. Skipping upload.", flush=True)
        upload_input = None

    # 1. Fill/upload inputs first
    if upload_input:
        sel = get_selector(upload_input) or "input[type='file']"
        return {
            "response": {
                "action": "upload",
                "selector": sel,
                "value": "",
                "reasoning": "Uploading resume.",
            }
        }

    # Handle custom dropdowns (VietnamWorks secondary profile form)
    dropdown_resp = handle_secondary_form_dropdowns(elements, is_secondary_form_open)
    if dropdown_resp is not None:
        return dropdown_resp

    # Scoped check for visa/work authorization questions on the page
    is_visa_question = False
    is_auth_question = False
    for el in elements:
        el_text = strip_vietnamese_accents(
            str(el.get("text", "") or el.get("aria_label", "") or "")
        )
        if any(x in el_text for x in ("visa", "sponsor", "sponsorship")):
            is_visa_question = True
        if any(
            x in el_text
            for x in (
                "authorized",
                "legal",
                "right to work",
                "permit",
                "work authorization",
            )
        ):
            is_auth_question = True

    # 2. Radios
    radio_resp = handle_radios(
        elements, radios, is_max_cvs_modal, is_visa_question, is_auth_question
    )
    if radio_resp is not None:
        return radio_resp

    # 3. Selects
    select_resp = handle_selects(selects, is_visa_question, is_auth_question)
    if select_resp is not None:
        return select_resp

    # 4. Text inputs
    text_resp = handle_text_inputs(text_inputs)
    if text_resp is not None:
        return text_resp

    # 5. Checkboxes
    cb_resp = handle_checkboxes(checkboxes)
    if cb_resp is not None:
        return cb_resp

    # 6. Cookie Consent
    cookie_resp = handle_cookie_consent(elements)
    if cookie_resp is not None:
        return cookie_resp

    # 7. Autofill, progress, and entry-point buttons
    return handle_autofill_and_buttons(elements)


def call_antigravity(
    prompt: str, json_mode: bool = False, image_b64: str = None
) -> str:
    global ready_count
    import uuid

    if not json_mode:
        if "SCREENING QUESTION FROM THE FORM:" in prompt:
            try:
                # Extract the screening question
                idx_q = prompt.find("SCREENING QUESTION FROM THE FORM:")
                q_sec = prompt[idx_q:]
                start_quote = q_sec.find('"')
                end_quote = q_sec.find('"', start_quote + 1)
                question_text = ""
                if start_quote != -1 and end_quote != -1:
                    question_text = q_sec[start_quote + 1 : end_quote].lower().strip()

                # Default fallback values
                answer = "Yes"
                if any(
                    x in question_text
                    for x in ("experience", "years", "năm", "kinh nghiệm")
                ):
                    answer = "5"
                elif any(
                    x in question_text
                    for x in ("salary", "pay", "compensation", "lương", "thu nhập")
                ):
                    answer = "Negotiable"
                elif any(
                    x in question_text for x in ("visa", "sponsor", "sponsorship")
                ):
                    answer = "No"
                elif any(
                    x in question_text
                    for x in ("authorized", "legal", "right to work", "permit")
                ):
                    answer = "Yes"
                elif (
                    "notice period" in question_text
                    or "start date" in question_text
                    or "availab" in question_text
                ):
                    answer = "Immediately"
                else:
                    if (
                        "yes or no" in question_text
                        or "yes/no" in question_text
                        or "?" in question_text
                    ):
                        answer = "Yes"

                print(
                    f"[IPC] Handled text screening question locally: '{question_text}' => '{answer}'",
                    flush=True,
                )
                return answer
            except Exception as e:
                print(f"[IPC WARNING] Text question resolver error: {e}", flush=True)
    global ready_count

    if json_mode:
        try:
            local_resp = get_visual_agent_response(prompt, "local")
            if local_resp and isinstance(local_resp, dict) and "response" in local_resp:
                inner_res = local_resp["response"]
                if isinstance(inner_res, dict):
                    data = json.dumps(inner_res, ensure_ascii=False)
                else:
                    data = str(inner_res)
                print(
                    "[IPC] Handled visual agent request locally using rules.",
                    flush=True,
                )
                return data
        except Exception as le:
            print(f"[IPC WARNING] Local responder error: {le}", flush=True)

    IPC_DIR.mkdir(parents=True, exist_ok=True)

    req_id = str(uuid.uuid4())
    req_file = IPC_DIR / f"request_{req_id}.json"
    resp_file = IPC_DIR / f"response_{req_id}.json"
    pending_file = IPC_DIR / "pending_request.json"

    payload = {"prompt": prompt, "json_mode": json_mode}
    if image_b64:
        payload["image_b64"] = image_b64

    try:
        # 1. Write request to pending_request.json (for interceptor to read)
        with open(pending_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        try:
            with open(req_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception as e:
            print(f"[IPC ERROR] Failed to write {req_file.name}: {e}", flush=True)

        # Automatically decode and save screenshot for daemon agent consumption
        if image_b64:
            try:
                import base64

                traj_id = os.environ.get("ANTIGRAVITY_TRAJECTORY_ID")
                if traj_id:
                    scratch_dir = (
                        Path("C:/Users/user/.gemini/antigravity/brain")
                        / traj_id
                        / "scratch"
                    )
                else:
                    scratch_dir = Path(__file__).resolve().parent.parent / "scratch"
                scratch_dir.mkdir(parents=True, exist_ok=True)
                img_path = scratch_dir / f"screenshot_{req_id}.png"
                with open(img_path, "wb") as fh:
                    fh.write(base64.b64decode(image_b64))
                print(
                    f"[IPC] Decoded and saved screenshot for daemon: {img_path.name}",
                    flush=True,
                )
            except Exception as e_img:
                print(
                    f"[IPC ERROR] Failed to decode/save screenshot: {e_img}", flush=True
                )

        with ready_lock:
            ready_count += 1
            current_count = ready_count

        # 2. Print READY signal to standard output so the interceptor catches it
        print(f"===READY_{current_count}==={resp_file.name}===", flush=True)

        # 3. Wait for response file
        start_time = time.time()
        timeout = float(os.environ.get("IPC_TIMEOUT", "10.0"))
        while not resp_file.exists():
            if time.time() - start_time > timeout:
                raise TimeoutError(
                    f"IPC request {req_id} timed out waiting for response after {timeout} seconds."
                )
            time.sleep(0.5)

        # 4. Read response
        data = None
        for attempt in range(200):
            try:
                time.sleep(0.5)
                with open(resp_file, encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    try:
                        traj_id = os.environ.get("ANTIGRAVITY_TRAJECTORY_ID")
                        if traj_id:
                            debug_log_path = (
                                Path("C:/Users/user/.gemini/antigravity/brain")
                                / traj_id
                                / "scratch"
                                / "ipc_debug.log"
                            )
                        else:
                            debug_log_path = (
                                Path(__file__).resolve().parent.parent
                                / "scratch"
                                / "ipc_debug.log"
                            )

                        debug_log_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(
                            debug_log_path,
                            "a",
                            encoding="utf-8",
                        ) as debug_file:
                            debug_file.write(f"\n--- REQUEST {req_id} ---\n{content}\n")
                    except Exception as e_log:
                        print(f"[IPC WARNING] Failed to write debug log: {e_log}")
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict) and "response" in parsed:
                            data = parsed["response"]
                        else:
                            data = parsed
                        break
                    except json.JSONDecodeError:
                        if content.startswith("{") or content.startswith("["):
                            continue
                        data = content
                        break
            except (FileNotFoundError, PermissionError):
                pass

        if data is None:
            raise RuntimeError(
                f"Failed to read valid response from {resp_file} after 200 attempts."
            )

        if isinstance(data, str):
            import re

            match = re.search(r"```json\s*(.*?)\s*```", data, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1).strip())
                except Exception:
                    pass
            else:
                clean_str = data.strip()
                if clean_str.startswith("{") or clean_str.startswith("["):
                    try:
                        data = json.loads(clean_str)
                    except Exception:
                        pass

        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False)

        print(
            f"[IPC] Received response from Antigravity for request {req_id}.",
            flush=True,
        )
        return data
    finally:
        # Clean up files
        for attempt in range(5):
            try:
                if req_file.exists():
                    req_file.unlink()
                if resp_file.exists():
                    resp_file.unlink()
                if pending_file.exists():
                    pending_file.unlink()
                break
            except:
                time.sleep(0.5)


def is_interceptor_available() -> bool:
    """Checks if the background IPC daemon is running and heartbeating within 30s."""
    import os
    import time

    heartbeat_file = IPC_DIR / "daemon_heartbeat.json"
    if heartbeat_file.exists():
        try:
            mtime = heartbeat_file.stat().st_mtime
            if time.time() - mtime < 30.0:
                return True
        except Exception:
            pass

    if os.environ.get("JOBHUNTER_TEST") == "1":
        return True

    return False
