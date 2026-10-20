#!/usr/bin/env python3
"""
review_and_tailor_cv.py — Standalone AI CV Reviewer & Tailoring Tool.

Allows anyone to quickly:
1. Audit and review an existing CV (PDF or TXT) against ATS standards or a target JD.
2. Tailor a CV to a target Job Description and render a clean vector PDF.

Usage:
  # Review / Audit CV:
  python scripts/review_and_tailor_cv.py --cv path/to/cv.pdf

  # Review against a target JD:
  python scripts/review_and_tailor_cv.py --cv path/to/cv.pdf --jd path/to/jd.txt

  # Tailor CV and output PDF:
  python scripts/review_and_tailor_cv.py --cv path/to/cv.pdf --jd path/to/jd.txt --mode tailor --output my_tailored_cv.pdf
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared_platform.cv_text import load_cv_text
from shared_platform.llm_client import GeminiClient


def review_cv(cv_text: str, jd_text: str = "") -> str:
    """Reviews CV against professional standards or a specific JD."""
    client = GeminiClient()

    if jd_text:
        prompt = f"""
You are a senior recruitment director and expert ATS auditor.
Conduct a rigorous audit of the following Candidate CV against the Target Job Description.

TARGET JOB DESCRIPTION:
{jd_text}

CANDIDATE CV:
{cv_text}

Provide a structured, highly actionable report in Vietnamese (or English if CV is in English) with:
1. Executive Summary & Match Score (/100)
2. Strong Alignments & High-Value Highlights
3. Critical Gaps & Missing Keywords (ATS filter risks)
4. Concrete Rewriting Suggestions (provide before/after for 3-5 key bullet points using STAR / Google XYZ formula)
5. Interview Preparation Focus Areas (potential red flags or probe questions)
"""
    else:
        prompt = f"""
You are a senior recruitment director and expert ATS auditor.
Conduct a thorough, professional audit of the following Candidate CV.

CANDIDATE CV:
{cv_text}

Provide a structured, highly actionable report in Vietnamese (or English if CV is in English) with:
1. Overall Impression & Professional Assessment
2. ATS Formatting & Structure Compliance
3. Content & Impact Analysis (quantifiable achievements, action verbs, clarity)
4. Weaknesses & Formatting Pitfalls to Eliminate
5. Concrete Rewriting Suggestions (provide before/after for 3-5 key bullet points using STAR / Google XYZ formula)
6. Recommended Next Steps for Optimization
"""

    print("[AI] Analyzing CV with Gemini AI...")
    return client.call(prompt, json_mode=False, timeout=60.0)


def tailor_cv(cv_text: str, jd_text: str, output_pdf: str) -> str:
    """Tailors CV to a target JD and renders to PDF."""
    from scripts.tailor_jd import generate_tailored_html, _render_pdf

    template_path = PROJECT_ROOT / "templates" / "resume_template.html"
    if not template_path.exists():
        template_path = PROJECT_ROOT / "templates" / "cv_template.html"

    with open(template_path, encoding="utf-8") as f:
        template_html = f.read()

    print("[AI] Tailoring CV content to match JD...")
    tailored_html = generate_tailored_html(jd_text, cv_text, template_html)

    out_pdf_path = Path(output_pdf).resolve()
    out_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    html_out_path = str(out_pdf_path).replace(".pdf", ".html")

    with open(html_out_path, "w", encoding="utf-8") as f:
        f.write(tailored_html)

    render_script = str(PROJECT_ROOT / "scripts" / "render_pdf.py")
    _render_pdf(html_out_path, str(out_pdf_path), render_script)
    return str(out_pdf_path)


def main():
    parser = argparse.ArgumentParser(description="AI CV Reviewer & Tailoring Tool")
    parser.add_argument("--cv", required=True, help="Path to CV file (.pdf or .txt)")
    parser.add_argument("--jd", default="", help="Path to Job Description file (.txt) or job description text")
    parser.add_argument(
        "--mode",
        choices=["review", "tailor", "both"],
        default="review",
        help="Operation mode: review (default), tailor, or both",
    )
    parser.add_argument("--output", default="", help="Output path for report (.md) or tailored CV (.pdf)")
    args = parser.parse_args()

    if not os.path.exists(args.cv):
        print(f"Error: CV file not found at {args.cv}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading CV from {args.cv}...")
    cv_text = load_cv_text(args.cv)

    jd_text = ""
    if args.jd:
        if os.path.exists(args.jd):
            with open(args.jd, encoding="utf-8") as f:
                jd_text = f.read()
        else:
            jd_text = args.jd

    if args.mode in ("review", "both"):
        report = review_cv(cv_text, jd_text)
        print("\n" + "=" * 50 + "\nAI CV AUDIT REPORT\n" + "=" * 50 + "\n")
        print(report)

        if args.output and args.output.endswith(".md"):
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"\nSaved audit report to {args.output}")

    if args.mode in ("tailor", "both"):
        if not jd_text:
            print("Error: Tailoring mode requires a Job Description (--jd).", file=sys.stderr)
            sys.exit(1)
        pdf_out = args.output if (args.output and args.output.endswith(".pdf")) else "tailored_cv.pdf"
        generated = tailor_cv(cv_text, jd_text, pdf_out)
        print(f"\nSuccessfully generated tailored CV PDF at: {generated}")


if __name__ == "__main__":
    main()
