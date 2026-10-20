"""
core/cookie_sentry.py — Automated Session Cookie Expiration Sentry & Pre-Flight Gate.

Proactively monitors session cookie validity, calculates TTL, probes active endpoints,
blocks unsafe headless apply attempts on expired cookies, and dispatches Telegram alerts.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger("JobHunter.CookieSentry")

KIT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_FILE = KIT_ROOT / "scripts" / "state.json"

# Authoritative cookie token definitions by portal
PLATFORM_PRIMARY_COOKIES: dict[str, list[str]] = {
    "linkedin": ["li_at"],
    "topcv": ["access_token", "topcv_session"],
    "indeed": ["jsessionid", "ctk", "SURF"],
    "uob": ["wday_vps_cookie", "CALYPSO_SESSION", "PLAY_SESSION"],
}

# Live probe endpoints by platform
PLATFORM_PROBE_URLS: dict[str, str] = {
    "linkedin": "https://www.linkedin.com/feed/",
    "topcv": "https://www.topcv.vn/tai-khoan/cai-dat-thong-tin",
    "indeed": "https://my.indeed.com/p/my-jobs",
}

# Throttle alerts: record last alert timestamp per platform
_LAST_ALERT_TIMESTAMPS: dict[str, float] = {}
ALERT_THROTTLE_SECONDS = 3600.0  # 1 hour throttle per platform


class CookieStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    MISSING = "MISSING"
    CHALLENGED = "CHALLENGED"


@dataclass
class SessionValidationResult:
    platform: str
    status: CookieStatus
    is_valid: bool
    ttl_seconds: float
    expires_at: str
    message: str
    probed: bool = False

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "status": self.status.value,
            "is_valid": self.is_valid,
            "ttl_seconds": round(self.ttl_seconds, 1),
            "expires_at": self.expires_at,
            "message": self.message,
            "probed": self.probed,
        }


class CookieSentry:
    """
    Automated Sentry for session cookies.
    Provides TTL evaluation, active session probing, and pre-flight apply gates.
    """

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or DEFAULT_STATE_FILE

    def _load_cookies(self) -> list[dict]:
        """Loads cookies list safely from state.json."""
        if not self.state_path.exists():
            return []
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("cookies", [])
        except Exception as e:
            logger.warning("[CookieSentry] Failed to load %s: %s", self.state_path, e)
            return []

    def check_ttl(self, platform: str = "linkedin") -> SessionValidationResult:
        """
        Calculates remaining Time-To-Live (TTL) for the platform's primary session cookie.
        """
        cookies = self._load_cookies()
        if not cookies:
            return SessionValidationResult(
                platform=platform,
                status=CookieStatus.MISSING,
                is_valid=False,
                ttl_seconds=0.0,
                expires_at="N/A",
                message=f"state.json missing or empty at {self.state_path}",
            )

        target_names = PLATFORM_PRIMARY_COOKIES.get(platform.lower(), ["li_at"])
        matched_cookies = [c for c in cookies if c.get("name") in target_names]

        if not matched_cookies:
            return SessionValidationResult(
                platform=platform,
                status=CookieStatus.MISSING,
                is_valid=False,
                ttl_seconds=0.0,
                expires_at="N/A",
                message=f"Primary session cookie ({'/'.join(target_names)}) not found in state.json",
            )

        # Evaluate TTL across matched cookies (take the minimum TTL for strict protection)
        now = time.time()
        min_ttl = float("inf")
        primary_cookie = matched_cookies[0]
        has_explicit_expiry = False

        for c in matched_cookies:
            exp = c.get("expires", c.get("expirationDate", -1))
            try:
                exp_val = float(exp)
            except (ValueError, TypeError):
                exp_val = -1

            if exp_val > 0:
                has_explicit_expiry = True
                ttl = exp_val - now
                if ttl < min_ttl:
                    min_ttl = ttl
                    primary_cookie = c

        if not has_explicit_expiry:
            # Session cookie with no explicit expiration (valid until browser close / server revoke)
            return SessionValidationResult(
                platform=platform,
                status=CookieStatus.ACTIVE,
                is_valid=True,
                ttl_seconds=86400.0 * 30,  # Estimated 30 days
                expires_at="Session (No explicit expiry timestamp)",
                message=f"{platform.capitalize()} session cookie '{primary_cookie.get('name')}' present (Session).",
            )

        exp_timestamp = primary_cookie.get(
            "expires", primary_cookie.get("expirationDate")
        )
        exp_readable = time.ctime(float(exp_timestamp))

        if min_ttl <= 0:
            return SessionValidationResult(
                platform=platform,
                status=CookieStatus.EXPIRED,
                is_valid=False,
                ttl_seconds=min_ttl,
                expires_at=exp_readable,
                message=f"{platform.capitalize()} session cookie expired on {exp_readable} (TTL: {min_ttl:.0f}s)",
            )

        # Warning threshold: less than 24 hours (86,400s)
        if min_ttl <= 86400:
            hours_left = min_ttl / 3600.0
            return SessionValidationResult(
                platform=platform,
                status=CookieStatus.EXPIRING_SOON,
                is_valid=True,
                ttl_seconds=min_ttl,
                expires_at=exp_readable,
                message=f"{platform.capitalize()} session cookie expires soon in {hours_left:.1f} hours ({exp_readable})",
            )

        days_left = min_ttl / 86400.0
        return SessionValidationResult(
            platform=platform,
            status=CookieStatus.ACTIVE,
            is_valid=True,
            ttl_seconds=min_ttl,
            expires_at=exp_readable,
            message=f"{platform.capitalize()} session cookie active. Valid for {days_left:.1f} more days ({exp_readable})",
        )

    def probe_live_session(
        self, platform: str = "linkedin", timeout_s: float = 6.0
    ) -> SessionValidationResult:
        """
        Performs a lightweight HTTP probe to verify whether the session cookie
        is actively accepted by the remote portal without launching a full browser.
        """
        ttl_result = self.check_ttl(platform)
        if not ttl_result.is_valid:
            ttl_result.probed = True
            return ttl_result

        probe_url = PLATFORM_PROBE_URLS.get(platform.lower())
        if not probe_url:
            ttl_result.probed = True
            return ttl_result

        cookies = self._load_cookies()
        cookie_header_parts = []
        for c in cookies:
            domain = c.get("domain", "")
            if platform.lower() in domain or (
                platform.lower() == "linkedin" and "linkedin.com" in domain
            ):
                cookie_header_parts.append(f"{c.get('name')}={c.get('value')}")

        if not cookie_header_parts:
            return SessionValidationResult(
                platform=platform,
                status=CookieStatus.MISSING,
                is_valid=False,
                ttl_seconds=0.0,
                expires_at="N/A",
                message=f"No cookies found matching domain for {platform}",
                probed=True,
            )

        cookie_header = "; ".join(cookie_header_parts)
        req = urllib.request.Request(
            probe_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Cookie": cookie_header,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        )

        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def http_error_302(self, req, fp, code, msg, headers):
                return fp

            http_error_301 = http_error_302
            http_error_303 = http_error_302
            http_error_307 = http_error_302

        try:
            opener = urllib.request.build_opener(NoRedirectHandler)
            with opener.open(req, timeout=timeout_s) as resp:
                status_code = getattr(resp, "status", 200)
                location = resp.headers.get("Location", "")

                # Check for redirect to authwall or login
                if any(
                    x in location
                    for x in [
                        "/uas/login",
                        "/login",
                        "checkpoint",
                        "authwall",
                        "challenge",
                    ]
                ):
                    return SessionValidationResult(
                        platform=platform,
                        status=CookieStatus.CHALLENGED,
                        is_valid=False,
                        ttl_seconds=0.0,
                        expires_at=ttl_result.expires_at,
                        message=f"{platform.capitalize()} session challenged or redirected to: {location}",
                        probed=True,
                    )

                if status_code in (401, 403):
                    return SessionValidationResult(
                        platform=platform,
                        status=CookieStatus.EXPIRED,
                        is_valid=False,
                        ttl_seconds=0.0,
                        expires_at=ttl_result.expires_at,
                        message=f"{platform.capitalize()} session probe rejected with HTTP {status_code}",
                        probed=True,
                    )

                ttl_result.probed = True
                return ttl_result

        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return SessionValidationResult(
                    platform=platform,
                    status=CookieStatus.EXPIRED,
                    is_valid=False,
                    ttl_seconds=0.0,
                    expires_at=ttl_result.expires_at,
                    message=f"{platform.capitalize()} session probe failed with HTTP {e.code}",
                    probed=True,
                )
            # Other errors (e.g. 500, 429 rate limit) - rely on TTL result
            ttl_result.probed = True
            return ttl_result
        except Exception as e:
            logger.debug("[CookieSentry] Probe network error (%s): %s", platform, e)
            ttl_result.probed = True
            return ttl_result

    def assert_apply_session_valid(
        self,
        platform: str = "linkedin",
        auto_alert: bool = True,
        probe: bool = False,
    ) -> tuple[bool, str]:
        """
        Pre-flight gate for apply workers.
        Returns (True, message) if session is safe to use.
        Returns (False, message) and dispatches a throttled Telegram alert if expired/invalid.
        """
        result = (
            self.probe_live_session(platform) if probe else self.check_ttl(platform)
        )

        if result.is_valid:
            return True, result.message

        # Session is invalid or challenged
        warning_msg = (
            f"🚨 [COOKIE SENTRY ALERT] {platform.upper()} session cookie is {result.status.value}!\n"
            f"Reason: {result.message}\n"
            f"Automated apply queue for {platform} is PAUSED to prevent bot challenges.\n"
            f"Action: Run 'python scripts/login_linkedin.py' in a visible terminal to re-authenticate."
        )
        logger.error(warning_msg)

        if auto_alert:
            self._dispatch_throttled_alert(platform, warning_msg)

        return False, result.message

    def _dispatch_throttled_alert(self, platform: str, message: str) -> None:
        """Sends Telegram notification throttled to once per hour per platform."""
        global _LAST_ALERT_TIMESTAMPS
        now = time.time()
        last_alert = _LAST_ALERT_TIMESTAMPS.get(platform, 0.0)

        if now - last_alert < ALERT_THROTTLE_SECONDS:
            logger.info(
                "[CookieSentry] Alert for %s throttled (last sent %.0fs ago)",
                platform,
                now - last_alert,
            )
            return

        try:
            from shared_platform.notify import send_telegram  # type: ignore

            send_telegram(message)
            _LAST_ALERT_TIMESTAMPS[platform] = now
            logger.info(
                "[CookieSentry] Telegram alert dispatched successfully for %s", platform
            )
        except Exception as e:
            logger.warning("[CookieSentry] Could not dispatch Telegram alert: %s", e)


# Global singleton instance for easy import
cookie_sentry = CookieSentry()
