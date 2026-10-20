"""
gmail_otp_reader.py — Reads the latest OTP/passcode from Gmail for JobHunterKit.

This module is used by the IPC interceptor to automatically retrieve email
OTPs (e.g. from Allianz SAP SuccessFactors) and pass them back to the pipeline.

Usage:
    from scripts.gmail_otp_reader import get_latest_otp
    otp = get_latest_otp(sender_hint="allianz")
"""

import base64
import os
import re
import sys
from pathlib import Path

# GmailSync skill path
GMAIL_SYNC_SKILL = Path(
    os.environ.get(
        "GMAIL_SYNC_SKILL_DIR",
        str(Path.home() / ".gemini" / "antigravity" / "skills" / "GmailSync"),
    )
)
GMAIL_SYNC_SRC = GMAIL_SYNC_SKILL / "src"
VAULT_GMAIL_DIR = Path(
    os.environ.get("GMAIL_VAULT_DIR", str(Path.home() / ".gemini" / "vault" / "gmail"))
)

if GMAIL_SYNC_SKILL.exists() and str(GMAIL_SYNC_SKILL) not in sys.path:
    sys.path.insert(0, str(GMAIL_SYNC_SKILL))
if GMAIL_SYNC_SRC.exists() and str(GMAIL_SYNC_SRC) not in sys.path:
    sys.path.insert(0, str(GMAIL_SYNC_SRC))


def _get_configured_gmail_accounts() -> list[str]:
    """Retrieve configured Gmail accounts from environment or AgentCredentialVault."""
    raw = os.getenv("GMAIL_USERS", os.getenv("GMAIL_USER", ""))
    if not raw:
        for mod_name, cls_name in [
            ("agentic_os.vault", "AgentCredentialVault"),
            ("scripts.agent_credential_vault", "AgentCredentialVault"),
        ]:
            try:
                mod = __import__(mod_name, fromlist=[cls_name])
                vault_cls = getattr(mod, cls_name)
                v = vault_cls().get_secret("GMAIL_USERS") or vault_cls().get_secret(
                    "GMAIL_USER"
                )
                if v:
                    raw = str(v).strip()
                    break
            except Exception:
                pass

    accounts = [e.strip() for e in raw.split(",") if e.strip()]
    if not accounts:
        raise RuntimeError(
            "GMAIL_USER or GMAIL_USERS must be set in environment or AgentCredentialVault"
        )
    return accounts


def _get_gmail_service(email: str | None = None):
    """Build an authenticated Gmail service for the given or default email."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    configured_accounts = _get_configured_gmail_accounts()
    target_email = email if (email and email != "applicant@example.com") else configured_accounts[0]

    token_slug = target_email.replace("@", "_at_")
    token_candidates = [
        VAULT_GMAIL_DIR / f"token_{token_slug}.json",
        GMAIL_SYNC_SKILL / f"token_{token_slug}.json",
    ]

    token_path = None
    for cand in token_candidates:
        if cand.exists():
            token_path = cand
            break

    if not token_path or not token_path.exists():
        raise FileNotFoundError(
            f"No Gmail token found for {target_email}. Configure GMAIL_VAULT_DIR and run auth_all.py first."
        )

    creds = Credentials.from_authorized_user_file(
        str(token_path), ["https://www.googleapis.com/auth/gmail.modify"]
    )
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def _extract_text_from_message(msg_data: dict) -> str:
    """Recursively extract plain text or HTML from a Gmail message payload."""
    payload = msg_data.get("payload", {})

    def _decode_part(part):
        data = part.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return ""

    def _walk(part):
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            return _decode_part(part)
        elif mime == "text/html":
            text = _decode_part(part)
            # Strip HTML tags
            return re.sub(r"<[^>]+>", " ", text)
        elif "parts" in part:
            for subpart in part["parts"]:
                result = _walk(subpart)
                if result:
                    return result
        return ""

    return _walk(payload) or msg_data.get("snippet", "")


def get_latest_otp(
    email: str | None = None,
    sender_hint: str = "allianz",
    max_age_minutes: int = 30,
    poll_interval: int = 5,
    poll_timeout: int = 120,
) -> str | None:
    """
    Polls Gmail for the latest OTP email from a given sender, extracts the passcode.

    Args:
        email: Gmail account to check. If None, uses first account from GMAIL_USER/GMAIL_USERS.
        sender_hint: Keyword to filter sender/subject (case-insensitive).
        max_age_minutes: Only consider emails received within this many minutes.
        poll_interval: Seconds between polls.
        poll_timeout: Total seconds to wait for an OTP email.

    Returns:
        The OTP string if found, None otherwise.
    """
    import time as _time

    configured = _get_configured_gmail_accounts()
    active_email = email if (email and email != "applicant@example.com") else configured[0]

    print(f"[GmailOTP] Polling {active_email} for OTP from '{sender_hint}'...")
    service = _get_gmail_service(active_email)

    start = _time.time()
    seen_ids = set()

    while _time.time() - start < poll_timeout:
        try:
            # Search for recent emails matching hint
            query = f"from:{sender_hint} newer_than:{max_age_minutes}m"
            results = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=5)
                .execute()
            )

            messages = results.get("messages", [])
            for msg in messages:
                msg_id = msg["id"]
                if msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)

                msg_data = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="full")
                    .execute()
                )

                body = _extract_text_from_message(msg_data)
                snippet = msg_data.get("snippet", "")
                full_text = body + " " + snippet

                # Extract OTP patterns: 4-8 digit numbers or alphanumeric codes
                patterns = [
                    r"[Pp]asscode[:\s]+([A-Z0-9]{4,10})",
                    r"[Oo]ne[- ][Tt]ime [Pp]assword[:\s]+([A-Z0-9]{4,10})",
                    r"[Vv]erification [Cc]ode[:\s]+([A-Z0-9]{4,10})",
                    r"[Cc]ode[:\s]+([A-Z0-9]{4,10})",
                    r"\b([0-9]{6,8})\b",  # bare 6-8 digit OTP
                ]

                for pattern in patterns:
                    match = re.search(pattern, full_text)
                    if match:
                        otp = match.group(1).strip()
                        print(f"[GmailOTP] Found OTP: {otp} (from email ID {msg_id})")
                        return otp

        except Exception as e:
            print(f"[GmailOTP] Error polling Gmail: {e}")

        print(f"[GmailOTP] No OTP found yet. Retrying in {poll_interval}s...")
        _time.sleep(poll_interval)

    print(f"[GmailOTP] Timed out after {poll_timeout}s. No OTP found.")
    return None


if __name__ == "__main__":
    try:
        otp = get_latest_otp(
            sender_hint="allianz",
            poll_timeout=10,
        )
        print(f"OTP Result: {otp}")
    except RuntimeError as e:
        print(f"Config validation verified: {e}")
