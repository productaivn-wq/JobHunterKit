"""
cookie_manager.py — Utilities for importing, merging, and converting session cookies
for Playwright storageState in JobHunterKit, and updating .env credentials.
"""

import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))


@contextmanager
def acquire_cross_process_lock(lock_file_path: Path, timeout: int = 10):
    lock_file = lock_file_path.with_suffix(".lock")
    start_time = time.time()
    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Could not acquire lock {lock_file}")
            time.sleep(0.1)
    try:
        yield
    finally:
        os.close(fd)
        try:
            os.remove(lock_file)
        except OSError:
            pass


STATE_FILE = KIT_ROOT / "scripts" / "state.json"
ENV_FILE = KIT_ROOT / ".env"

UOB_RAW_COOKIES = [
    {
        "domain": "uobgroup.wd3.myworkdayjobs.com",
        "hostOnly": True,
        "httpOnly": True,
        "name": "wday_vps_cookie",
        "path": "/",
        "sameSite": "no_restriction",
        "secure": True,
        "session": True,
        "storeId": None,
        "value": "sample_cookie_val_1",
    },
    {
        "domain": "uobgroup.wd3.myworkdayjobs.com",
        "hostOnly": True,
        "httpOnly": False,
        "name": "PLAY_LANG",
        "path": "/",
        "sameSite": "lax",
        "secure": False,
        "session": True,
        "storeId": None,
        "value": "en-US",
    },
]


def convert_raw_cookie_to_playwright(cookie: dict) -> dict:
    """Converts standard/browser JSON cookie format into Playwright storageState cookie format."""
    same_site_raw = str(cookie.get("sameSite", "")).lower()
    if same_site_raw == "no_restriction" or same_site_raw == "none":
        same_site = "None"
    elif same_site_raw == "strict":
        same_site = "Strict"
    else:
        same_site = "Lax"

    try:
        exp = float(cookie.get("expirationDate", cookie.get("expires", -1)))
    except (ValueError, TypeError):
        exp = -1

    secure = bool(cookie.get("secure", False))
    if same_site == "None":
        secure = True

    pw_cookie = {
        "name": cookie.get("name", ""),
        "value": str(cookie.get("value", "")),
        "domain": cookie.get("domain", ""),
        "path": cookie.get("path", "/"),
        "expires": exp if exp != -1 else -1,
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "secure": secure,
        "sameSite": same_site,
    }
    return pw_cookie


def merge_cookies_into_state(raw_cookies: list, state_path: Path = STATE_FILE):
    """Merges raw cookie list into state.json, updating existing matching domain/name cookies."""
    state_data = {"cookies": [], "origins": []}

    with acquire_cross_process_lock(state_path):
        if state_path.exists():
            try:
                with open(state_path, encoding="utf-8") as f:
                    state_data = json.load(f)
            except Exception as e:
                print(f"[CookieManager] Warning reading existing state.json: {e}")

        existing_cookies = state_data.get("cookies", [])
        cookie_map = {
            (c.get("domain", ""), c.get("path", "/"), c.get("name", "")): c
            for c in existing_cookies
        }

        added_count = 0
        updated_count = 0
        for raw in raw_cookies:
            pw_c = convert_raw_cookie_to_playwright(raw)
            key = (pw_c["domain"], pw_c["path"], pw_c["name"])
            if key in cookie_map:
                cookie_map[key].update(pw_c)
                updated_count += 1
            else:
                cookie_map[key] = pw_c
                added_count += 1

        state_data["cookies"] = list(cookie_map.values())

        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)

    print(
        f"[CookieManager] Successfully saved to {state_path}: {added_count} added, {updated_count} updated."
    )
    return state_data


def update_env_variable(key: str, value: str, env_path: Path = ENV_FILE):
    """Safely updates or adds a key=value pair in .env file."""
    os.environ[key] = str(value)
    root_env = Path("./.env")

    for path in [env_path, root_env]:
        lines = []
        found = False
        if path.exists():
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()

        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f'{key}="{value}"\n')
                found = True
            else:
                new_lines.append(line)

        if not found:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append(f'{key}="{value}"\n')

        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    print(f"[CookieManager] Updated .env with {key}={value}")


def get_cookie_status(platform: str = "linkedin") -> dict:
    """Returns structured CookieSentry status dictionary for the given platform."""
    from core.cookie_sentry import cookie_sentry

    return cookie_sentry.check_ttl(platform).to_dict()


def is_cookie_valid(platform: str = "linkedin", probe: bool = False) -> bool:
    """Convenience boolean check for platform session validity."""
    from core.cookie_sentry import cookie_sentry

    if probe:
        return cookie_sentry.probe_live_session(platform).is_valid
    return cookie_sentry.check_ttl(platform).is_valid


def ingest_uob_cookies_and_env():
    """Ingests the provided UOB cookies into state.json and sets default env variables."""
    merge_cookies_into_state(UOB_RAW_COOKIES)
    update_env_variable("CANDIDATE_EMAIL", "applicant@example.com")
    update_env_variable("WORKDAY_DEFAULT_PASSWORD", "JobHunter2026!")
    update_env_variable("UOB_WORKDAY_EMAIL", "applicant@example.com")
    update_env_variable("UOB_WORKDAY_PASSWORD", "JobHunter2026!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        plat = sys.argv[2] if len(sys.argv) > 2 else "linkedin"
        print(json.dumps(get_cookie_status(plat), indent=2))
    else:
        ingest_uob_cookies_and_env()
