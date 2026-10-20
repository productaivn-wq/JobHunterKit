"""
Shared CV Loader Platform Layer for JobHunterKit.
Consolidates CV text extraction logic supporting both PDF and raw text files.
"""

import os


def load_cv_text(cv_path: str) -> str:
    """
    Loads and extracts text from the candidate's CV file.
    Supports PDF files via PyMuPDF (fitz) and standard text files.
    """
    if not cv_path or not os.path.exists(cv_path):
        raise FileNotFoundError(f"CV file not found: {cv_path}")

    if cv_path.lower().endswith(".pdf"):
        import fitz

        doc = fitz.open(cv_path)
        text = "".join(page.get_text() for page in doc)
        doc.close()
        return text
    else:
        with open(cv_path, encoding="utf-8") as f:
            return f.read()
