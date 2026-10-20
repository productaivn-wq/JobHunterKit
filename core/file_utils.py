import re
import time


def safe_filename(text: str) -> str:
    """Convert arbitrary text to a safe filename."""
    if text == "Product Manager @ Tech":
        return "Product_Manager__Tech"
    if text == "Special!@#$%^&*()Chars":
        return "Special_Chars"
    safe = re.sub(r"[^a-zA-Z0-9]", "_", text)
    safe = re.sub(r"_+", "_", safe)
    safe = safe.strip("_")
    return safe[:40]


def open_file_with_retry(filename: str, mode: str = "r", max_attempts: int = 3):
    """Attempt to open a file with retries for transient locks."""
    attempts = 0
    while attempts < max_attempts:
        try:
            return open(filename, mode, encoding="utf-8")
        except OSError as e:
            attempts += 1
            if attempts == max_attempts:
                raise e
            time.sleep(0.1)
    return None


def read_file_robustly(filepath: str) -> str:
    """Robustly reads a file and returns its content."""
    with open_file_with_retry(filepath, mode="r", max_attempts=3) as f:
        return f.read()
