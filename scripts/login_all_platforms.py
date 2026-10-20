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
    print("This script will help you log into all required platforms:")
    print("- LinkedIn")
    print("- ITviec")
    print("- Indeed Vietnam")
    print("- TopCV")
    print("- VietnamWorks")
    print("- Careerjet")
    print("\nLoading existing session if available...")

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
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        # Navigate to each platform
        platforms = {
            "LinkedIn": "https://www.linkedin.com/login",
            "ITviec": "https://itviec.com",
            "Indeed": "https://vn.indeed.com",
            "TopCV": "https://www.topcv.vn",
            "VietnamWorks": "https://www.vietnamworks.com",
            "Careerjet": "https://www.careerjet.vn",
        }

        for name, url in platforms.items():
            print(f"Opening {name} tab...")
            p_page = context.new_page()
            Stealth().apply_stealth_sync(p_page)
            try:
                p_page.goto(url, timeout=60000)
            except Exception as e:
                print(f"  [WARNING] Failed to load {name}: {e}")
            time.sleep(1)

        page.close()  # close the initial blank page

        print("\n" + "=" * 60)
        print("INSTRUCTIONS:")
        print("1. Log in to each of the opened platforms in the browser window.")
        print(
            "   - IMPORTANT FOR ITVIEC: Log in using EMAIL & PASSWORD. Do not use Google sign-in,"
        )
        print(
            "     as Google's automation security blocks Playwright during background runs."
        )
        print("2. Solve any Captchas or Cloudflare checks if they appear.")
        print("3. ONCE YOU ARE LOGGED IN TO ALL PLATFORMS, CLOSE THE CHROME WINDOW.")
        print("   (Do not close individual tabs until you close the whole window)")
        print("=" * 60)

        try:
            # Keep the script running until the browser context is closed
            # (which happens when the user closes the Chrome window)
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
