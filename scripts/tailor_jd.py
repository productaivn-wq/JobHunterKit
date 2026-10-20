import argparse
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")


def extract_text(file_path):
    if file_path.lower().endswith(".pdf"):
        import fitz

        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    with open(file_path, encoding="utf-8") as f:
        return f.read()


KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if KIT_DIR not in sys.path:
    sys.path.insert(0, KIT_DIR)

from core.retry_utils import _call_llm_unified

PROFILE_PATH = os.path.join(
    KIT_DIR,
    "config",
    "applicant_profile.json",
)


def load_applicant_profile() -> dict:
    try:
        if os.path.exists(PROFILE_PATH):
            with open(PROFILE_PATH, encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"Warning: Failed to read applicant_profile.json at {PROFILE_PATH}: {e}")
        return {}


def load_prompt(name: str, fallback_template: str) -> str:
    """Loads a prompt template from config/prompts/{name}.txt, falling back to an in-code generic template."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(
        os.path.dirname(script_dir),
        "config",
        "prompts",
        f"{name}.txt",
    )
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"[WARNING] Failed to read prompt from {prompt_path}: {e}")
    return fallback_template


TAILOR_CV_PROMPT_TEMPLATE_FALLBACK = """
You are an expert Resume Tailoring assistant. Adapt the candidate's Base CV to match the Job Description (JD).
Use the provided HTML template and replace the placeholders (e.g. {{TARGET_JOB_TITLE_OR_SIMILAR}}, {{2_SENTENCE_PUNCHY_SUMMARY}}, {{JOB_ROLE}}, {{KEYWORD_1}}, {{BULLET_POINT_1}}) with authentic CV data.

JOB DESCRIPTION:
{jd_text}

CANDIDATE CV:
{cv_text}

HTML TEMPLATE:
{template_html}
"""


def generate_tailored_html(jd_text, cv_text, template_html):
    """Generates tailored CV HTML based on Job Description. (UC-004)"""
    print("[UTOP|func|generate_tailored_html|cp-fr-011]")
    load_applicant_profile()
    prompt = load_prompt("tailor_cv", TAILOR_CV_PROMPT_TEMPLATE_FALLBACK).format(
        jd_text=jd_text,
        cv_text=cv_text,
        template_html=template_html,
    )

    print("Calling LLM to tailor CV...")
    tailored_html = _call_llm_unified(prompt, "", json_mode=False)

    if "```html" in tailored_html:
        tailored_html = tailored_html.split("```html")[1].split("```")[0].strip()
    elif tailored_html.startswith("```"):
        tailored_html = tailored_html[3:].split("```")[0].strip()

    return tailored_html


def _read_tailor_inputs(args, template_path):
    """Reads the JD, CV, and template HTML files."""
    try:
        jd_text = extract_text(args.jd_file)
        cv_text = extract_text(args.cv_file)
        with open(template_path, encoding="utf-8") as f:
            template_html = f.read()
        return jd_text, cv_text, template_html
    except Exception as e:
        print(f"Failed to read input files: {e}")
        sys.exit(1)


def _render_pdf(html_out_path, pdf_out_path, render_script):
    """Renders the HTML file to a PDF using ResumeTailorKit's render_pdf.py."""
    print("Rendering PDF via ResumeTailorKit...")
    render_cmd = [
        sys.executable,
        render_script,
        html_out_path,
        pdf_out_path,
        "--type",
        "resume",
    ]
    result = subprocess.run(render_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Failed to render PDF: {result.stderr}")
        sys.exit(1)
    print(f"Successfully generated {pdf_out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Tailor a CV to a JD and generate a PDF using ResumeTailorKit.",
    )
    parser.add_argument(
        "--job-id",
        required=True,
        help="Job ID for file naming (e.g., job_1)",
    )
    parser.add_argument(
        "--jd-file",
        required=True,
        help="Path to the Job Description text file",
    )
    parser.add_argument("--cv-file", required=True, help="Path to the Base CV file")
    parser.add_argument(
        "--output-pdf",
        required=True,
        help="Full output path for the tailored PDF",
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    kit_dir = os.path.dirname(script_dir)

    local_template_path = os.path.join(kit_dir, "templates", "resume_template.html")
    local_render_script = os.path.join(script_dir, "render_pdf.py")

    if os.path.exists(local_template_path) and os.path.exists(local_render_script):
        template_path = local_template_path
        render_script = local_render_script
    else:
        resume_kit_dir = os.path.join(kit_dir, "..", "ResumeTailorKit")
        template_path = os.path.join(
            resume_kit_dir,
            "templates",
            "resume_template.html",
        )
        render_script = os.path.join(resume_kit_dir, "scripts", "render_pdf.py")

    jd_text, cv_text, template_html = _read_tailor_inputs(args, template_path)

    print(f"Generating tailored HTML for {args.job_id}...")
    tailored_html = generate_tailored_html(jd_text, cv_text, template_html)

    if not tailored_html:
        print("Failed to generate tailored HTML.")
        sys.exit(1)

    # Perform dynamic PII substitution to secure candidate identity in public repository
    profile = load_applicant_profile()
    personal = profile.get("personal", {})
    full_name = personal.get("full_name", "Jane Doe")
    phone = personal.get("phone", "+1-555-0199")
    email = personal.get("email", "jane.doe@example.com")
    city = personal.get("city", "City")
    country = personal.get("country", "Country")
    location = (
        f"{city}, {country}"
        if city and country
        else (city or country or "City, Country")
    )
    linkedin_url = personal.get("linkedin", "linkedin.com/in/jane-doe")

    tailored_html = tailored_html.replace("{FULL_NAME}", full_name)
    tailored_html = tailored_html.replace("{LOCATION}", location)
    tailored_html = tailored_html.replace("{PHONE}", phone)
    tailored_html = tailored_html.replace("{EMAIL}", email)
    tailored_html = tailored_html.replace("{LINKEDIN_URL}", linkedin_url)

    pdf_out_path = os.path.abspath(args.output_pdf)
    os.makedirs(os.path.dirname(pdf_out_path), exist_ok=True)
    html_out_path = pdf_out_path.replace(".pdf", ".html")
    with open(html_out_path, "w", encoding="utf-8") as f:
        f.write(tailored_html)

    _render_pdf(html_out_path, pdf_out_path, render_script)
    sys.exit(0)


if __name__ == "__main__":
    main()
