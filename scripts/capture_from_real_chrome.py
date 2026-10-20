"""
capture_from_real_chrome.py — Universal Real Chrome Auth Capture for Channels & Enterprise ATS.

Launches genuine Google Chrome with remote debugging on port 9222, opening tabs for:
  1. Primary Job Platforms (LinkedIn, ITviec, TopCV, VietnamWorks, Google SSO)
  2. Enterprise ATS Portals (Workday, Taleo, Greenhouse, BrassRing, Lever, SmartRecruiters)
  3. Active pending/manual-intervention job URLs directly from PostgreSQL

Bypasses Cloudflare bot detection, Google SSO restrictions, and 2FA challenges by capturing
genuine authenticated storage state into scripts/state.json via Chrome DevTools Protocol (CDP).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
STATE_FILE = SCRIPT_DIR / "state.json"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

# Canonical Enterprise ATS Portals (Focus: Workday & Greenhouse)
ENTERPRISE_ATS_URLS = [
    # Workday Portals
    "https://nab.wd3.myworkdayjobs.com/nab_careers/login",
    "https://propertyguru.wd105.myworkdayjobs.com/PropertyGuru/login",
    # Greenhouse
    "https://boards.greenhouse.io",
]

# Primary Job Channels
PRIMARY_CHANNELS_URLS = [
    "https://www.linkedin.com/login",
    "https://itviec.com/sign_in",
    "https://www.topcv.vn/login",
    "https://www.vietnamworks.com/login",
    "https://accounts.google.com",
]


def find_chrome_executable() -> str:
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    return "chrome.exe"


def fetch_active_db_urls(limit: int = 5) -> list[str]:
    """Fetches active external job URLs from PostgreSQL that need authentication."""
    try:
        from core.db_client import get_connection

        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT url FROM job_hunter.jobs
                WHERE (status_apply = 'needs_manual_intervention' OR status_apply = 'pending')
                  AND url IS NOT NULL
                  AND (
                      url ILIKE '%workday%' OR url ILIKE '%myworkdayjobs%' OR
                      url ILIKE '%greenhouse%'
                  )
                ORDER BY id DESC
                LIMIT %s;
            """,
                (limit,),
            )
            rows = cur.fetchall()
            return [r[0] for r in rows if r[0]]
    except Exception as e:
        print(f"  [Notice] Could not query active DB URLs (skipping dynamic URLs): {e}")
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Real Chrome CDP Authentication Capture"
    )
    parser.add_argument(
        "--ats-only",
        action="store_true",
        help="Open only Enterprise ATS portals (Workday, Taleo, Greenhouse, Lever, etc.)",
    )
    parser.add_argument(
        "--channels-only",
        action="store_true",
        help="Open only primary job board channels (LinkedIn, ITviec, TopCV, VietnamWorks)",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Do not fetch dynamic pending URLs from database",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Specific custom URL(s) to open for authentication",
    )
    args = parser.parse_args()

    print("=" * 75)
    print("   UNIVERSAL REAL CHROME AUTHENTICATION & ATS SESSION CAPTURE")
    print("=" * 75)

    target_urls = []

    if args.url:
        target_urls.extend(args.url)

    if args.ats_only:
        target_urls.extend(ENTERPRISE_ATS_URLS)
    elif args.channels_only:
        target_urls.extend(PRIMARY_CHANNELS_URLS)
    else:
        # Default: Open both primary channels and major Enterprise ATS portals
        target_urls.extend(PRIMARY_CHANNELS_URLS)
        target_urls.extend(ENTERPRISE_ATS_URLS)

    if not args.no_db and not args.channels_only:
        db_urls = fetch_active_db_urls(limit=4)
        for u in db_urls:
            if u not in target_urls:
                target_urls.append(u)

    chrome_exe = find_chrome_executable()
    temp_profile = os.path.join(
        os.environ.get("TEMP", "C:\\Temp"), "JobHunterChromeProfile"
    )
    os.makedirs(temp_profile, exist_ok=True)

    print(f"\n1. Chrome Executable : {chrome_exe}")
    print(f"2. User Profile Dir  : {temp_profile}")
    print("3. Remote Debug Port : 9222")
    print(f"\n4. Tabs To Open ({len(target_urls)} portals):")
    for i, u in enumerate(target_urls, 1):
        domain = urlparse(u).netloc or u
        print(f"   [{i:02d}] {domain:<35} -> {u[:65]}")

    cmd = [
        chrome_exe,
        "--remote-debugging-port=9222",
        f"--user-data-dir={temp_profile}",
    ] + target_urls

    print("\nLaunching Google Chrome with remote debugging enabled...")
    try:
        subprocess.Popen(cmd)
    except Exception as e:
        print(f"[ERROR] Failed to start Chrome: {e}")
        print("Please start Chrome manually via terminal:")
        print(
            f'  "{chrome_exe}" --remote-debugging-port=9222 --user-data-dir="{temp_profile}"'
        )
        sys.exit(1)

    print("\n" + "=" * 75)
    print("INSTRUCTIONS:")
    print(
        "1. In the Chrome window that just opened, log into your accounts across the tabs:"
    )
    print("   • Primary: LinkedIn, ITviec, TopCV, VietnamWorks, Google SSO")
    print(
        "   • Enterprise ATS: Workday (NAB, PropertyGuru), Greenhouse, Lever, SmartRecruiters, Taleo, BrassRing"
    )
    print("2. Solve any 2FA / SMS / Captchas as prompted in genuine Chrome.")
    print(
        "3. When you have finished logging in, PRESS ENTER HERE in this terminal."
    )
    print("=" * 75)

    try:
        input(
            "\n>>> Press ENTER once you have completed logins to capture session & cookies... "
        )
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)

    print("\nConnecting to Chrome over CDP (http://localhost:9222)...")
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            contexts = browser.contexts
            if not contexts:
                print("[ERROR] No browser contexts found.")
                sys.exit(1)

            context = contexts[0]
            print(
                "Extracting storage state (cookies, local storage, authorization tokens)..."
            )
            context.storage_state(path=str(STATE_FILE))
            print(f"[SUCCESS] Saved authenticated session to: {STATE_FILE}")

            # Summarize cookies captured
            with open(STATE_FILE, encoding="utf-8") as f:
                saved_data = json.load(f)
            cookies = saved_data.get("cookies", [])
            domains = set(c.get("domain", "") for c in cookies)
            print(
                f"\nCaptured {len(cookies)} cookies across {len(domains)} domains:"
            )
            for d in sorted(domains):
                print(f"  ✓ {d}")

            print("\n" + "=" * 75)
            print(
                "✅ All sessions captured! Flow 3 can now apply autonomously without stopping."
            )
            print("You can now close the Chrome window.")
            print("=" * 75)

        except Exception as e:
            print(f"[ERROR] Failed to capture session over CDP: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()

