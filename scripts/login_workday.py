import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Load .env from the JobHunterKit root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr:
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    state_file = os.path.join(script_dir, "state.json")

    # Manual login scripts must always run headfully to allow interactive login/2FA
    headless = False
    print("This script will help you log into the Workday portals for:")
    print("1. NAB (National Australia Bank)")
    print("2. PropertyGuru")
    print("\nLoading existing session state...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, channel="chrome")
        if os.path.exists(state_file):
            print(f"Applying existing session from {state_file}...")
            context = browser.new_context(
                storage_state=state_file,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
        else:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

        # Open NAB login tab
        print("Opening NAB Careers login tab...")
        nab_page = context.new_page()
        Stealth().apply_stealth_sync(nab_page)
        try:
            nab_page.goto(
                "https://nab.wd3.myworkdayjobs.com/nab_careers/login", timeout=60000
            )
        except Exception as e:
            print(f"  [WARNING] Failed to load NAB: {e}")

        # Open PropertyGuru login tab
        print("Opening PropertyGuru Careers login tab...")
        pg_page = context.new_page()
        Stealth().apply_stealth_sync(pg_page)
        try:
            pg_page.goto(
                "https://propertyguru.wd105.myworkdayjobs.com/PropertyGuru/login",
                timeout=60000,
            )
        except Exception as e:
            print(f"  [WARNING] Failed to load PropertyGuru: {e}")

        print("\n" + "=" * 60)
        print("INSTRUCTIONS:")
        print("1. Log in or create/register a candidate account on BOTH portals.")
        print("2. Use email: applicant@example.com")
        print("3. Solve any Captchas or verification if they appear.")
        print("4. ONCE YOU ARE LOGGED IN TO BOTH PORTALS, CLOSE THE CHROME WINDOW.")
        print("   (Do not close individual tabs until you close the whole window)")
        print("=" * 60)

        try:
            # Keep the script running until the browser context is closed
            while len(context.pages) > 0:
                time.sleep(1)
        except Exception:
            pass

        print("\nBrowser closed! Saving authentication state to state.json...")
        try:
            context.storage_state(path=state_file)
            print(f"[SUCCESS] Saved combined cookies & authentication to: {state_file}")
        except Exception as e:
            print(f"[ERROR] Failed to save storage state: {e}")

        browser.close()


if __name__ == "__main__":
    main()
