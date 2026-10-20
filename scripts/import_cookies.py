"""
import_cookies.py — Imports exported browser cookies into JobHunterKit state.json.

Supports JSON cookie format exported by Cookie-Editor, EditThisCookie, or raw Playwright storageState.
Usage:
  python scripts/import_cookies.py --file path/to/cookies.json
  python scripts/import_cookies.py --text '[{"name": "...", ...}]'
  python scripts/import_cookies.py --clipboard
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from scripts.cookie_manager import merge_cookies_into_state, STATE_FILE


def main():
    parser = argparse.ArgumentParser(description="Import cookies into JobHunterKit state.json")
    parser.add_argument("--file", "-f", help="Path to JSON file containing cookies")
    parser.add_argument("--text", "-t", help="Raw JSON string containing cookies")
    parser.add_argument("--clipboard", "-c", action="store_true", help="Read cookie JSON from clipboard")
    args = parser.parse_args()

    raw_data = None

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"[ERROR] File not found: {file_path}")
            sys.exit(1)
        with open(file_path, encoding="utf-8") as f:
            raw_data = json.load(f)

    elif args.text:
        raw_data = json.loads(args.text)

    elif args.clipboard:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            clip_text = root.clipboard_get()
            raw_data = json.loads(clip_text)
            print("[INFO] Read JSON cookie data from clipboard.")
        except Exception as e:
            print(f"[ERROR] Could not read JSON from clipboard: {e}")
            print("Please provide a file via --file <path> instead.")
            sys.exit(1)

    else:
        print("[ERROR] Please provide --file <path>, --text '<json>', or --clipboard")
        print("Example: python scripts/import_cookies.py --file my_exported_cookies.json")
        sys.exit(1)

    # If raw_data is a dictionary with 'cookies' key (e.g. Playwright storageState)
    if isinstance(raw_data, dict) and "cookies" in raw_data:
        cookie_list = raw_data["cookies"]
    elif isinstance(raw_data, list):
        cookie_list = raw_data
    else:
        print("[ERROR] Unexpected cookie format: expected a list or a dict with 'cookies' key.")
        sys.exit(1)

    print(f"Importing {len(cookie_list)} cookies into {STATE_FILE}...")
    merge_cookies_into_state(cookie_list, STATE_FILE)
    print("\n[SUCCESS] Cookies successfully imported and merged into state.json!")
    print("Run 'python scripts/verify_login.py' to check the status.")


if __name__ == "__main__":
    main()
