"""
Pre-Flight Health & Channel Authentication Checker for JobHunterKit.
Verifies channel authentication, DB connectivity, phase readiness, and daemon state before pipeline runs.
"""

import os
import sys
from pathlib import Path

# Add project root to python path
KIT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_ROOT))
sys.path.insert(0, str(KIT_ROOT / "scripts"))


def check_db_health() -> tuple[bool, str]:
    """Verifies database connection and basic query execution."""
    try:
        from core.db_client import get_connection

        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM job_hunter.jobs;")
            count = cur.fetchone()[0]
        conn.close()
        return True, f"DB Online ({count:,} jobs registered)"
    except Exception as e:
        return False, f"DB Connection Error: {e}"


def check_linkedin_auth_health() -> tuple[bool, str]:
    """
    Checks if LinkedIn session cookies exist in state.json,
    specifically verifying li_at presence, TTL, and expiration status via CookieSentry.
    """
    try:
        from core.cookie_sentry import cookie_sentry

        result = cookie_sentry.check_ttl("linkedin")
        return result.is_valid, result.message
    except Exception as e:
        return False, f"Failed to check LinkedIn cookie status: {e}"


def check_gmail_auth_health() -> tuple[bool, str]:
    """
    Validates Gmail OAuth token health by attempting a token refresh.
    This catches revoked/expired refresh tokens before they cause silent failures
    during OTP reads or email-based scraping (WI-PREV-02).
    """
    from dotenv import load_dotenv

    # Load project .env for Gmail credentials
    project_env = Path("./.env")
    if project_env.exists():
        load_dotenv(project_env)

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        missing = [
            k
            for k, v in {
                "GOOGLE_CLIENT_ID": client_id,
                "GOOGLE_CLIENT_SECRET": client_secret,
                "GMAIL_REFRESH_TOKEN": refresh_token,
            }.items()
            if not v
        ]
        return False, f"Gmail OAuth credentials missing: {', '.join(missing)}"

    try:
        import urllib.parse
        import urllib.request

        data = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json as _json

            token_data = _json.loads(resp.read())
            if "access_token" in token_data:
                expires_in = token_data.get("expires_in", "unknown")
                return (
                    True,
                    f"Gmail OAuth Active (token refreshable, expires in {expires_in}s)",
                )
            else:
                return (
                    False,
                    f"Gmail token refresh returned no access_token: {token_data}",
                )
    except urllib.error.HTTPError as e:
        try:
            import json as _json

            error_body = _json.loads(e.read())
            error_desc = error_body.get(
                "error_description", error_body.get("error", str(e))
            )
        except Exception:
            error_desc = str(e)
        return False, f"Gmail OAuth FAILED: {error_desc}"
    except Exception as e:
        return False, f"Gmail OAuth check error: {e}"


def check_llm_health() -> tuple[bool, str]:
    """Checks if LLM routing (GeminiClient → LLMProviderRouter → antigravity_cli) is functional."""
    try:
        from shared_platform.llm_client import GeminiClient

        client = GeminiClient()
        if client.router is None:
            return (
                False,
                "LLMProviderRouter not available (TaskManager not in sys.path)",
            )
        result = client.call("Respond with exactly: OK", json_mode=False)
        if isinstance(result, str) and result.strip():
            return True, "LLM Routing Active (LLMProviderRouter → antigravity_cli)"
        return False, f"LLM returned unexpected result type: {type(result).__name__}"
    except Exception as e:
        return False, f"LLM health check failed: {e}"


def validate_env_secrets() -> tuple[bool, str]:
    """
    Validates that required secret environment variables are set.
    Logs warnings for missing variables without exposing values.
    """
    from dotenv import load_dotenv

    # Load kit local .env
    kit_env = KIT_ROOT / ".env"
    if kit_env.exists():
        load_dotenv(kit_env)

    # Load project level .env
    project_env = Path("./.env")
    if project_env.exists():
        load_dotenv(project_env)

    required_vars = [
        "DB_URL",
        "TWOCAPTCHA_API_KEY",
        "GMAIL_USER",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GMAIL_REFRESH_TOKEN",
    ]

    missing = []
    for var in required_vars:
        if not os.environ.get(var):
            missing.append(var)

    if missing:
        return False, f"Missing required env vars: {', '.join(missing)}"

    return True, "All required secrets are present"


def check_channel_health() -> dict:
    """
    Returns a comprehensive health check matrix for all pipeline channels.
    """
    li_ok, li_msg = check_linkedin_auth_health()
    db_ok, db_msg = check_db_health()
    llm_ok, llm_msg = check_llm_health()
    gmail_ok, gmail_msg = check_gmail_auth_health()

    channels = {
        "linkedin": {"ok": li_ok, "detail": li_msg, "type": "auth_cookie"},
        "gmail": {"ok": gmail_ok, "detail": gmail_msg, "type": "oauth"},
        "database": {"ok": db_ok, "detail": db_msg, "type": "infrastructure"},
        "llm_routing": {"ok": llm_ok, "detail": llm_msg, "type": "cli"},
        "topcv": {"ok": True, "detail": "Public Scrape Ready", "type": "public"},
        "itviec": {"ok": True, "detail": "Public Scrape Ready", "type": "public"},
        "vietnamworks": {"ok": True, "detail": "Public Scrape Ready", "type": "public"},
        "glints": {"ok": True, "detail": "Public Scrape Ready", "type": "public"},
        "indeed": {"ok": True, "detail": "Public Scrape Ready", "type": "public"},
        "careerjet": {"ok": True, "detail": "Public Scrape Ready", "type": "public"},
    }
    return channels


def run_preflight_checks(flow_name: str = "pipeline") -> tuple[bool, str]:
    """
    Executes pre-flight checks before running a flow phase.
    Logs diagnostic summary and returns (is_healthy, summary_string).
    """
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print(f"--- [PRE-FLIGHT HEALTH CHECK: {flow_name.upper()}] ---")

    db_ok, db_msg = check_db_health()
    li_ok, li_msg = check_linkedin_auth_health()
    llm_ok, llm_msg = check_llm_health()
    env_ok, env_msg = validate_env_secrets()
    gmail_ok, gmail_msg = check_gmail_auth_health()

    print(f"  • Database Health: {'🟢' if db_ok else '🔴'} {db_msg}")
    print(f"  • LinkedIn Auth:   {'🟢' if li_ok else '🔴'} {li_msg}")
    print(f"  • Gmail OAuth:     {'🟢' if gmail_ok else '🔴'} {gmail_msg}")
    print(f"  • LLM Routing:     {'🟢' if llm_ok else '🟡'} {llm_msg}")
    print(f"  • Secrets/Env:     {'🟢' if env_ok else '🟡'} {env_msg}")

    # Flow-specific enforcement rules
    if flow_name == "flow1_scrape":
        # Scrape needs DB, and if source is linkedin, needs LinkedIn auth
        if not db_ok:
            return False, f"Pre-flight failed for {flow_name}: {db_msg}"
        if not gmail_ok:
            print(
                "  [WARNING] Gmail OAuth is invalid; jobright_gmail scraper will be unavailable."
            )

    elif flow_name == "flow2_score":
        if not db_ok:
            return False, f"Pre-flight failed for {flow_name}: {db_msg}"

    elif flow_name == "flow3_apply":
        if not db_ok:
            return False, f"Pre-flight failed for {flow_name}: {db_msg}"
        if not li_ok:
            print(
                "  [WARNING] LinkedIn Auth is invalid; LinkedIn applications will be flagged for manual intervention."
            )
        if not gmail_ok:
            print(
                "  [WARNING] Gmail OAuth is invalid; OTP-gated applications will fail."
            )

    summary = f"Pre-flight OK (DB: {db_ok}, LinkedIn: {li_ok}, Gmail: {gmail_ok}, LLM: {llm_ok})"
    print(f"--- [PRE-FLIGHT COMPLETE: {summary}] ---\n")
    return True, summary


if __name__ == "__main__":
    run_preflight_checks("diagnostic")
