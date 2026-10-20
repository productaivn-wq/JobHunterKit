import argparse
import os
import sys

from playwright.sync_api import sync_playwright


def render_html_to_pdf(html_path, pdf_path, doc_type="cv"):
    """Renders an HTML file to a PDF using Playwright."""
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    if not os.path.exists(html_path):
        print(f"Error: HTML file not found at {html_path}")
        sys.exit(1)

    # Determine margins based on document type
    if doc_type == "cv":
        margins = {"top": "0.6in", "bottom": "0.6in", "left": "0.6in", "right": "0.6in"}
    elif doc_type == "resume":
        margins = {"top": "0.3in", "bottom": "0.3in", "left": "0.5in", "right": "0.5in"}
    elif doc_type == "cl":
        margins = {"top": "1.0in", "bottom": "1.0in", "left": "1.0in", "right": "1.0in"}
    else:
        margins = {"top": "0.6in", "bottom": "0.6in", "left": "0.6in", "right": "0.6in"}

    print(f"Rendering {html_path} to {pdf_path} (Type: {doc_type})...")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Resolve absolute path and replace backslashes for file:// URI
        abs_html_path = os.path.abspath(html_path)
        file_uri = f"file:///{abs_html_path.replace(chr(92), '/')}"

        page.goto(file_uri)

        # Wait for the Inter font to load
        page.evaluate("document.fonts.ready")

        # Emulate print media for accurate CSS rendering
        page.emulate_media(media="print")

        # Generate the PDF
        page.pdf(path=pdf_path, format="A4", print_background=True, margin=margins)

        browser.close()

    print(f"Successfully generated {pdf_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Render HTML to PDF for CVs and Cover Letters.",
    )
    parser.add_argument("input_html", help="Path to the input HTML file")
    parser.add_argument("output_pdf", help="Path for the output PDF file")
    parser.add_argument(
        "--type",
        choices=["cv", "resume", "cl"],
        default="cv",
        help="Document type (cv, resume, or cl) to determine margins",
    )

    args = parser.parse_args()

    render_html_to_pdf(args.input_html, args.output_pdf, args.type)
