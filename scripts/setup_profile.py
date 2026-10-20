"""JobHunterKit Onboarding: Generates applicant_profile.json from a CV file.

Usage:
    python setup_profile.py --cv-file path/to/your_cv.pdf

What it does:
    1. Parses the CV using Gemini LLM to extract structured profile data
       (experience years by domain, education, skills, etc.)
    2. Prompts you interactively for info that can't be extracted from a CV
       (phone, salary expectation, work preferences)
    3. Writes config/applicant_profile.json for the pipeline to use

This must be run once before using the pipeline for the first time.
"""

import argparse
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KIT_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_DIR = os.path.join(KIT_DIR, "config")
PROFILE_PATH = os.path.join(CONFIG_DIR, "applicant_profile.json")

if KIT_DIR not in sys.path:
    sys.path.insert(0, KIT_DIR)

from core.retry_utils import _call_llm_unified


def extract_cv_text(cv_file: str) -> str:
    """Reads CV content from PDF or text file."""
    if cv_file.lower().endswith(".pdf"):
        try:
            import fitz

            doc = fitz.open(cv_file)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except ImportError:
            print("ERROR: PyMuPDF (fitz) is required to read PDF files.")
            print("  Install it with: pip install PyMuPDF")
            sys.exit(1)
    else:
        with open(cv_file, encoding="utf-8") as f:
            return f.read()


EXTRACT_CV_PROMPT_TEMPLATE = """
You are an expert CV/Resume parser. Analyze the following CV and extract structured profile data.

CV TEXT:
{cv_text}

Return a JSON object with EXACTLY this structure. Estimate years of experience for each domain
based on the work history dates and responsibilities described. Be realistic — only count years
where the person actually used that skill based on their described work.

{{
  "extracted_name": "<full name>",
  "extracted_email": "<email if found, else empty string>",
  "extracted_phone": "<phone if found, else empty string>",
  "extracted_city": "<city if found, else empty string>",
  "extracted_linkedin": "<linkedin URL if found, else empty string>",
  "experience_years": {{
    "total": <total years of professional experience>,
    "product_management": <years>,
    "ai_ml": <years>,
    "ux": <years of UX/user research/design thinking>,
    "data_analysis": <years>,
    "agile_scrum": <years>,
    "crm": <years>,
    "saas": <years of B2B/SaaS experience>,
    "leadership": <years of team/cross-functional leadership>,
    "project_management": <years>,
    "software_development": <years>,
    "marketing": <years>,
    "sales": <years>,
    "devops": <years>,
    "cloud": <years>,
    "no_code": <years>,
    "prompt_engineering": <years>,
    "llm": <years of LLM/GenAI experience>,
    "stakeholder_management": <years>,
    "people_management": <years>,
    "remote_work": <years>
  }},
  "education": {{
    "highest_degree": "<degree type>",
    "field": "<field of study>"
  }},
  "certifications": ["<cert 1>", "<cert 2>"]
}}
"""


def extract_profile_from_cv(cv_text: str) -> dict:
    """Uses Gemini LLM to extract structured profile data from CV text. (UC-001)
    Returns a dict with experience_years, education, and personal info found in CV.
    """
    print("[UTOP|func|extract_profile_from_cv|cp-fr-001]")
    from dotenv import load_dotenv

    env_path = os.path.join(os.path.dirname(KIT_DIR), ".env")
    for candidate in [
        env_path,
        os.path.join(os.path.expanduser("~"), ".gemini", ".env"),
        ".env",
    ]:
        if os.path.exists(candidate):
            load_dotenv(candidate)
            break

    # call_antigravity handles authentication via IPC — no GEMINI_API_KEY needed here
    api_key = None  # Kept as placeholder for _call_llm_unified compatibility

    prompt = EXTRACT_CV_PROMPT_TEMPLATE.format(cv_text=cv_text)
    try:
        response_text = _call_llm_unified(prompt, api_key, json_mode=True)
        # Clean markdown wrappers if any are returned
        cleaned = response_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        cleaned = cleaned.removesuffix("```")
        return json.loads(cleaned.strip())
    except Exception as e:
        print(f"ERROR: LLM extraction failed: {e}")
        print("Falling back to manual entry mode.")
        return None


def prompt_user(question: str, default: str = "") -> str:
    """Prompts user for input with an optional default value."""
    if default:
        answer = input(f"  {question} [{default}]: ").strip()
        return answer or default
    return input(f"  {question}: ").strip()


def prompt_user_number(question: str, default: int = 0) -> int:
    """Prompts user for a numeric input."""
    while True:
        answer = input(f"  {question} [{default}]: ").strip()
        if not answer:
            return default
        try:
            return int(answer)
        except ValueError:
            print("    Please enter a whole number.")


def _prompt_personal_info(ext: dict) -> dict:
    """Prompts user for personal info section."""
    print("\n--- Personal Information ---")
    print("  (Press Enter to accept the [default] value)\n")
    return {
        "full_name": prompt_user("Full name", ext.get("extracted_name", "")),
        "phone": prompt_user(
            "Phone number (with country code, e.g. +84...)",
            ext.get("extracted_phone", ""),
        ),
        "email": prompt_user("Email", ext.get("extracted_email", "")),
        "city": prompt_user("City", ext.get("extracted_city", "")),
        "linkedin": prompt_user("LinkedIn URL", ext.get("extracted_linkedin", "")),
    }


def _prompt_salary_info() -> dict:
    """Prompts user for salary info section."""
    print("\n--- Salary Information ---")
    print("  (This info is never in your CV but needed for application forms)\n")
    current_usd = prompt_user_number("Current monthly salary (USD)", 0)
    current_vnd = prompt_user_number(
        "Current monthly salary (VND)",
        current_usd * 25000 if current_usd else 0,
    )
    expected_usd = prompt_user_number(
        "Expected monthly salary (USD)",
        int(current_usd * 1.25) if current_usd else 0,
    )
    expected_vnd = prompt_user_number(
        "Expected monthly salary (VND)",
        expected_usd * 25000 if expected_usd else int(current_vnd * 1.25),
    )
    return {
        "current_usd": current_usd,
        "current_vnd": current_vnd,
        "expected_usd": expected_usd,
        "expected_vnd": expected_vnd,
        "_note": "Gross monthly.",
    }


def _prompt_experience_years(exp: dict) -> dict:
    """Prompts user for experience years section."""
    print("\n--- Experience Years ---")
    if exp:
        print("  (Auto-extracted from your CV. Review and adjust if needed)\n")
    else:
        print("  (Enter your years of experience for each domain)\n")

    fields = {
        "total": "Total professional experience",
        "product_management": "Product Management",
        "ai_ml": "AI / Machine Learning",
        "ux": "User Experience (UX)",
        "data_analysis": "Data Analysis",
        "agile_scrum": "Agile / Scrum",
        "crm": "CRM",
        "saas": "B2B / SaaS",
        "leadership": "Leadership",
        "project_management": "Project Management",
        "software_development": "Software Development",
        "marketing": "Marketing",
        "sales": "Sales",
        "devops": "DevOps",
        "cloud": "Cloud (AWS/GCP/Azure)",
        "no_code": "No-code / Low-code",
        "prompt_engineering": "Prompt Engineering",
        "llm": "LLM / GenAI",
        "stakeholder_management": "Stakeholder Management",
        "people_management": "People Management",
        "remote_work": "Remote Work",
    }
    experience = {}
    for key, label in fields.items():
        experience[key] = prompt_user_number(label, exp.get(key, 0))
    experience["_default"] = 3
    return experience


def build_profile_interactive(extracted: dict = None) -> dict:
    """Builds the complete applicant profile by combining LLM-extracted data (UC-001)
    with interactive user prompts for non-extractable information.
    """
    print("[UTOP|func|build_profile_interactive|cp-fr-002]")
    print("\n" + "=" * 60)
    print("  JobHunterKit Profile Setup")
    print("=" * 60)

    ext = extracted or {}
    exp = ext.get("experience_years", {})

    personal = _prompt_personal_info(ext)
    salary = _prompt_salary_info()
    experience = _prompt_experience_years(exp)

    print("\n--- Work Preferences ---\n")
    relocate = (
        prompt_user("Willing to relocate? (yes/no)", "yes").lower().startswith("y")
    )
    sponsorship = (
        prompt_user("Require visa sponsorship? (yes/no)", "no").lower().startswith("y")
    )
    notice_days = prompt_user_number("Notice period (days)", 30)

    edu = ext.get("education", {})
    personal["country"] = prompt_user("Country", "Vietnam")

    return {
        "_description": "Auto-generated applicant profile for JobHunterKit. Edit values anytime to update.",
        "_generated_by": "setup_profile.py",
        "personal": personal,
        "salary": salary,
        "experience_years": experience,
        "education": {
            "highest_degree": edu.get("highest_degree", ""),
            "field": edu.get("field", ""),
        },
        "work_authorization": {
            "authorized_to_work": True,
            "require_sponsorship": sponsorship,
            "notice_period_days": notice_days,
        },
        "languages": {
            "english": prompt_user(
                "English proficiency (Native/Professional/Conversational)",
                "Professional",
            ),
            "vietnamese": prompt_user(
                "Vietnamese proficiency (Native/Professional/Conversational)",
                "Native",
            ),
        },
        "preferences": {
            "willing_to_relocate": relocate,
            "work_type": ["On-site", "Hybrid", "Remote"],
            "start_availability": "Immediately"
            if notice_days <= 14
            else f"{notice_days} days notice",
            "campaigns": [
                {
                    "job_title": "Product Manager",
                    "places": ["Ho Chi Minh", "Hanoi", "Vietnam"],
                    "channels": ["linkedin", "itviec", "topcv", "vietnamworks"],
                },
                {
                    "job_title": "AI Product Manager",
                    "places": ["Ho Chi Minh", "Hanoi", "Vietnam"],
                    "channels": ["linkedin", "linkedin-recommended", "itviec"],
                },
                {
                    "job_title": "AI Product Director",
                    "places": ["Ho Chi Minh", "Hanoi", "Vietnam"],
                    "channels": ["linkedin", "linkedin-recommended", "itviec"],
                },
                {
                    "job_title": "Fullstack Developer",
                    "places": ["Remote"],
                    "channels": ["linkedin", "itviec"],
                },
            ],
        },
    }


def _build_non_interactive_profile(extracted: dict) -> dict:
    """Builds profile from extracted data with safe defaults (non-interactive)."""
    return {
        "_description": "Auto-generated applicant profile for JobHunterKit.",
        "_generated_by": "setup_profile.py (non-interactive)",
        "personal": {
            "full_name": extracted.get("extracted_name", ""),
            "phone": extracted.get("extracted_phone", ""),
            "email": extracted.get("extracted_email", ""),
            "city": extracted.get("extracted_city", ""),
            "country": "Vietnam",
            "linkedin": extracted.get("extracted_linkedin", ""),
        },
        "salary": {
            "current_usd": 0,
            "current_vnd": 0,
            "expected_usd": 0,
            "expected_vnd": 0,
            "_note": "UPDATE THESE VALUES — salary cannot be extracted from CV.",
        },
        "experience_years": {**extracted.get("experience_years", {}), "_default": 3},
        "education": extracted.get("education", {}),
        "work_authorization": {
            "authorized_to_work": True,
            "require_sponsorship": False,
            "notice_period_days": 30,
        },
        "languages": {"english": "Professional", "vietnamese": "Native"},
        "preferences": {
            "willing_to_relocate": True,
            "work_type": ["On-site", "Hybrid", "Remote"],
            "start_availability": "30 days notice",
            "campaigns": [
                {
                    "job_title": "Product Manager",
                    "places": ["Ho Chi Minh", "Hanoi", "Vietnam"],
                    "channels": ["linkedin", "itviec", "topcv", "vietnamworks"],
                },
                {
                    "job_title": "AI Product Manager",
                    "places": ["Ho Chi Minh", "Hanoi", "Vietnam"],
                    "channels": ["linkedin", "linkedin-recommended", "itviec"],
                },
                {
                    "job_title": "AI Product Director",
                    "places": ["Ho Chi Minh", "Hanoi", "Vietnam"],
                    "channels": ["linkedin", "linkedin-recommended", "itviec"],
                },
                {
                    "job_title": "Fullstack Developer",
                    "places": ["Remote"],
                    "channels": ["linkedin", "itviec"],
                },
            ],
        },
    }


def _save_profile_file(profile: dict):
    """Saves the applicant profile to disk, backing up the old one if needed."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(PROFILE_PATH):
        backup = PROFILE_PATH + ".bak"
        os.replace(PROFILE_PATH, backup)
        print(f"\n  Previous profile backed up to: {backup}")

    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"  Profile saved to: {PROFILE_PATH}")
    print("  You can edit this file anytime to update your info.")
    print("  Run the pipeline with:")
    print('    python scripts/pipeline.py --keyword "..." --location "..."')
    print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(
        description="JobHunterKit Profile Setup — Generate your applicant profile from your CV.",
        epilog="Run this once before using the pipeline. You can re-run anytime to update your profile.",
    )
    parser.add_argument(
        "--cv-file",
        required=True,
        help="Path to your CV/Resume (PDF or text file)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip interactive prompts (uses LLM extraction + defaults only)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.cv_file):
        print(f"ERROR: CV file not found: {args.cv_file}")
        sys.exit(1)

    print(f"Reading CV from: {args.cv_file}")
    cv_text = extract_cv_text(args.cv_file)
    print(f"  Extracted {len(cv_text)} characters of text.\n")

    print("Analyzing CV with AI to extract profile data...")
    extracted = extract_profile_from_cv(cv_text)

    if extracted:
        print("  AI extraction successful!")
        exp = extracted.get("experience_years", {})
        print(f"  Name: {extracted.get('extracted_name', 'N/A')}")
        print(f"  Total experience: {exp.get('total', '?')} years")
        print(f"  Product Management: {exp.get('product_management', '?')} years")
    else:
        print("  AI extraction failed. Proceeding with manual entry.")

    if args.non_interactive:
        if not extracted:
            print("ERROR: --non-interactive requires successful LLM extraction.")
            sys.exit(1)
        profile = _build_non_interactive_profile(extracted)
        print(
            "\n[WARNING] Salary fields set to 0 — edit config/applicant_profile.json to update.",
        )
    else:
        profile = build_profile_interactive(extracted)

    _save_profile_file(profile)


if __name__ == "__main__":
    main()
