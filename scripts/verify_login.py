"""
verify_login.py — Multi-Platform Session and Authentication Status Verifier.

Checks active cookies, tokens, and storage state in state.json across LinkedIn,
ITviec, and TopCV with stealth headers.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr:
    sys.stderr.reconfigure(encoding="utf-8")

script_dir = os.path.dirname(os.path.abspath(__file__))
state_file = os.path.join(script_dir, "state.json")
scratch_dir = os.path.join(os.path.dirname(script_dir), "scratch")
os.makedirs(scratch_dir, exist_ok=True)

print("==================================================")
print("     MULTI-PLATFORM AUTHENTICATION VERIFIER       ")
print("==================================================")

if not os.path.exists(state_file) or os.path.getsize(state_file) == 0:
    print(f"[ERROR] Session state file not found at: {state_file}")
    print("Please run 'python scripts/login_all_platforms.py' to login and save session.")
    sys.exit(1)

print(f"Loading session from: {state_file}...")

with sync_playwright() as p:
    try:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=state_file,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        results = {}

        # 1. Verify LinkedIn
        print("\nChecking LinkedIn session...")
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        try:
            page.goto("https://www.linkedin.com/feed/", timeout=25000)
            page.wait_for_timeout(3000)
            is_linkedin_auth = "Feed" in page.title() or page.locator("nav.global-nav").count() > 0
            results["LinkedIn"] = "ACTIVE" if is_linkedin_auth else "EXPIRED / NOT LOGGED IN"
        except Exception as e:
            results["LinkedIn"] = f"CHECK FAILED ({e})"
        finally:
            page.close()

        # 2. Verify ITviec
        print("Checking ITviec session...")
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        try:
            page.goto("https://itviec.com", timeout=25000)
            page.wait_for_timeout(3000)
            is_itviec_auth = page.locator("a[href*='/sign_out'], .user-avatar, [data-testid='user-menu']").count() > 0
            results["ITviec"] = "ACTIVE" if is_itviec_auth else "GUEST / NOT LOGGED IN"
        except Exception as e:
            results["ITviec"] = f"CHECK FAILED ({e})"
        finally:
            page.close()

        # 3. Verify TopCV
        print("Checking TopCV session...")
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        try:
            # Check cookie presence in storageState
            with open(state_file, encoding="utf-8") as sf:
                state_data = json.load(sf)
            topcv_cookies = [c for c in state_data.get("cookies", []) if "topcv" in c.get("domain", "")]
            has_session = any(c.get("name") in ["topcv_session", "sso_token"] for c in topcv_cookies)

            page.goto("https://www.topcv.vn/viec-lam", timeout=25000)
            page.wait_for_timeout(3000)
            
            is_topcv_auth = (
                page.locator(".dropdown-user, .user-avatar, .header-avatar, a[href*='dang-xuat'], a[href*='tai-khoan']").count() > 0
                or ("viec-lam" in page.url and has_session)
                or has_session
            )
            results["TopCV"] = "ACTIVE" if is_topcv_auth else "GUEST / NOT LOGGED IN"
        except Exception as e:
            results["TopCV"] = f"CHECK FAILED ({e})"
        finally:
            page.close()

        # 4. Verify VietnamWorks
        print("Checking VietnamWorks session...")
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        try:
            with open(state_file, encoding="utf-8") as sf:
                state_data = json.load(sf)
            vnw_cookies = [c for c in state_data.get("cookies", []) if "vietnamworks" in c.get("domain", "")]
            has_vnw = len(vnw_cookies) > 5

            page.goto("https://www.vietnamworks.com", timeout=25000)
            page.wait_for_timeout(3000)
            is_vnw_auth = (
                page.locator("a[href*='/logout'], .user-profile, .dropdown-user, .profile-avatar").count() > 0
                or has_vnw
            )
            results["VietnamWorks"] = "ACTIVE" if is_vnw_auth else "GUEST / NOT LOGGED IN"
        except Exception as e:
            results["VietnamWorks"] = f"CHECK FAILED ({e})"
        finally:
            page.close()

        browser.close()

        print("\n" + "=" * 50)
        print("           AUTHENTICATION SCORECARD               ")
        print("=" * 50)
        for platform, status in results.items():
            icon = "✅" if "ACTIVE" in status else "⚠️"
            print(f" {icon} {platform:<15}: {status}")
        print("=" * 50)

    except Exception as e:
        print(f"[ERROR] Verification failed: {e}")
        sys.exit(1)
