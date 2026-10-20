"""
login_linkedin.py — Interactive browser login session manager for LinkedIn.

Launches a visible Chromium session to permit manual login, SSO, and 2FA,
persisting the resulting cookies and storage state to state.json.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Load .env from the JobHunterKit root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def main() -> None:
    """Launches interactive browser for LinkedIn login and saves storage state upon closure."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    state_file = os.path.join(script_dir, "state.json")

    # Manual login scripts must always run headfully to allow interactive login/2FA
    headless = False
    print("Launching visible browser for LinkedIn login...")
    print("Please log in to your account, complete any captchas/2FA.")
    print("Once you see the LinkedIn Feed, close the browser window.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, channel="chrome")
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Apply stealth to bypass Google SSO "insecure browser" blocks
        Stealth().apply_stealth_sync(page)

        page.goto("https://www.linkedin.com/login")

        print("\nWaiting for you to close the browser...")

        # Keep the script running until the user closes the browser context
        try:
            page.wait_for_event("close", timeout=0)  # Wait indefinitely
        except Exception as we:
            print(f"Browser event listener exited: {we}")

        print("\nBrowser closed! Saving authentication state...")

        # Save storage state to a JSON file
        context.storage_state(path=state_file)
        print(f"[SUCCESS] Auth state saved to {state_file}")


if __name__ == "__main__":
    main()
