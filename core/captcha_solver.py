"""
CAPTCHA Solver Helper for JobHunterKit
======================================
Supports:
  - 2captcha API (hCaptcha, Cloudflare Turnstile)
  - CapSolver API (hCaptcha, Cloudflare Turnstile)
  - Manual fallback (signal file based)

Usage:
    from captcha_solver import CaptchaSolver
    solver = CaptchaSolver(api_key='YOUR_KEY', service='2captcha')
    token = solver.solve_hcaptcha(website_url, site_key)
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


class CaptchaSolver:
    """
    Unified CAPTCHA solver supporting 2captcha and capsolver APIs.
    Falls back to signal-file manual mode if no API key configured.
    """

    SERVICES = {
        "2captcha": {
            "submit": "https://2captcha.com/in.php",
            "result": "https://2captcha.com/res.php",
        },
        "capsolver": {
            "submit": "https://api.capsolver.com/createTask",
            "result": "https://api.capsolver.com/getTaskResult",
        },
    }

    def __init__(self, api_key: str = None, service: str = "2captcha"):
        self.api_key = (
            api_key
            or os.environ.get("TWOCAPTCHA_API_KEY")
            or os.environ.get("2CAPTCHA_API_KEY")
            or os.environ.get("CAPTCHA_API_KEY")
            or os.environ.get("CAPTCHA_SOLVER_API_KEY", "")
        )

        if not self.api_key:
            try:
                import sys
                from pathlib import Path

                project_root = Path(__file__).parent.parent.parent
                if str(project_root) not in sys.path:
                    sys.path.insert(0, str(project_root))
                from core.db_client import get_config_val

                self.api_key = get_config_val("captcha_api_key") or ""
            except Exception:
                pass
        self.service = service.lower()
        if self.service not in self.SERVICES:
            raise ValueError(
                f"Unsupported service: {service}. Use '2captcha' or 'capsolver'"
            )

    def _http_get(self, url: str, timeout: int = 30) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")

    def _http_post(self, url: str, data: dict, timeout: int = 30) -> str:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")

    # ─── 2captcha ──────────────────────────────────────────────────────────────

    def _2captcha_submit(self, params: dict) -> str:
        """Submit a task to 2captcha, return task ID."""
        params["key"] = self.api_key
        params["json"] = "1"
        qs = urllib.parse.urlencode(params)
        url = f"{self.SERVICES['2captcha']['submit']}?{qs}"
        resp = json.loads(self._http_get(url))
        if resp.get("status") != 1:
            raise RuntimeError(f"2captcha submit error: {resp}")
        return str(resp["request"])

    def _2captcha_poll(
        self, task_id: str, poll_interval: int = 10, timeout: int = 180
    ) -> str:
        """Poll 2captcha for result, return token."""
        url_base = self.SERVICES["2captcha"]["result"]
        elapsed = 0
        while elapsed < timeout:
            time.sleep(poll_interval)
            elapsed += poll_interval
            url = f"{url_base}?key={self.api_key}&action=get&id={task_id}&json=1"
            resp = json.loads(self._http_get(url))
            if resp.get("status") == 1:
                return resp["request"]
            if resp.get("request") != "CAPCHA_NOT_READY":
                raise RuntimeError(f"2captcha poll error: {resp}")
            print(f"  [2captcha] Waiting... ({elapsed}s / {timeout}s)")
        raise TimeoutError("2captcha timed out")

    def solve_hcaptcha_2captcha(self, website_url: str, site_key: str) -> str:
        print(f"  [2captcha] Submitting hCaptcha for sitekey={site_key[:20]}...")
        task_id = self._2captcha_submit(
            {
                "method": "hcaptcha",
                "sitekey": site_key,
                "pageurl": website_url,
            }
        )
        print(f"  [2captcha] Task ID: {task_id}. Polling...")
        return self._2captcha_poll(task_id)

    def solve_turnstile_2captcha(self, website_url: str, site_key: str) -> str:
        print(f"  [2captcha] Submitting Turnstile for sitekey={site_key[:20]}...")
        task_id = self._2captcha_submit(
            {
                "method": "turnstile",
                "sitekey": site_key,
                "pageurl": website_url,
            }
        )
        print(f"  [2captcha] Task ID: {task_id}. Polling...")
        return self._2captcha_poll(task_id)

    # ─── CapSolver ─────────────────────────────────────────────────────────────

    def _capsolver_submit(self, task: dict) -> str:
        """Submit a task to capsolver, return taskId."""
        payload = {"clientKey": self.api_key, "task": task}
        resp = json.loads(
            self._http_post(self.SERVICES["capsolver"]["submit"], payload)
        )
        if resp.get("errorId", 0) != 0:
            raise RuntimeError(f"CapSolver submit error: {resp}")
        return resp["taskId"]

    def _capsolver_poll(
        self, task_id: str, poll_interval: int = 5, timeout: int = 180
    ) -> dict:
        """Poll CapSolver for result."""
        url = self.SERVICES["capsolver"]["result"]
        elapsed = 0
        while elapsed < timeout:
            time.sleep(poll_interval)
            elapsed += poll_interval
            payload = {"clientKey": self.api_key, "taskId": task_id}
            resp = json.loads(self._http_post(url, payload))
            if resp.get("errorId", 0) != 0:
                raise RuntimeError(f"CapSolver error: {resp}")
            if resp.get("status") == "ready":
                return resp["solution"]
            print(f"  [capsolver] Waiting... ({elapsed}s / {timeout}s)")
        raise TimeoutError("CapSolver timed out")

    def solve_hcaptcha_capsolver(self, website_url: str, site_key: str) -> str:
        print(f"  [capsolver] Submitting hCaptcha for sitekey={site_key[:20]}...")
        task_id = self._capsolver_submit(
            {
                "type": "HCaptchaTaskProxyless",
                "websiteURL": website_url,
                "websiteKey": site_key,
            }
        )
        print(f"  [capsolver] Task ID: {task_id}. Polling...")
        solution = self._capsolver_poll(task_id)
        return solution.get("gRecaptchaResponse", solution.get("token", ""))

    def solve_turnstile_capsolver(self, website_url: str, site_key: str) -> str:
        print(f"  [capsolver] Submitting Turnstile for sitekey={site_key[:20]}...")
        task_id = self._capsolver_submit(
            {
                "type": "AntiTurnstileTaskProxyless",
                "websiteURL": website_url,
                "websiteKey": site_key,
            }
        )
        print(f"  [capsolver] Task ID: {task_id}. Polling...")
        solution = self._capsolver_poll(task_id)
        return solution.get("token", "")

    # ─── Public Interface ──────────────────────────────────────────────────────

    def solve_hcaptcha(self, website_url: str, site_key: str) -> str:
        """Solve hCaptcha using configured service. Returns response token."""
        if not self.api_key:
            raise ValueError(
                "No CAPTCHA API key configured. Set CAPTCHA_API_KEY env var."
            )
        if self.service == "2captcha":
            return self.solve_hcaptcha_2captcha(website_url, site_key)
        else:
            return self.solve_hcaptcha_capsolver(website_url, site_key)

    def solve_turnstile(self, website_url: str, site_key: str) -> str:
        """Solve Cloudflare Turnstile using configured service. Returns token."""
        if not self.api_key:
            raise ValueError(
                "No CAPTCHA API key configured. Set CAPTCHA_API_KEY env var."
            )
        if self.service == "2captcha":
            return self.solve_turnstile_2captcha(website_url, site_key)
        else:
            return self.solve_turnstile_capsolver(website_url, site_key)

    def check_balance(self) -> float:
        """Check remaining balance on 2captcha account."""
        if self.service == "2captcha":
            url = f"{self.SERVICES['2captcha']['result']}?key={self.api_key}&action=getbalance&json=1"
            resp = json.loads(self._http_get(url))
            if resp.get("status") == 1:
                return float(resp["request"])
            raise RuntimeError(f"Balance check error: {resp}")
        else:
            payload = {"clientKey": self.api_key}
            resp = json.loads(
                self._http_post("https://api.capsolver.com/getBalance", payload)
            )
            if resp.get("errorId", 0) == 0:
                return float(resp.get("balance", 0))
            raise RuntimeError(f"Balance check error: {resp}")


def inject_hcaptcha_token(page, token: str):
    """
    Inject a solved hCaptcha token into the page.
    Handles both standard and iframe scenarios.
    """
    js = f"""
        (function() {{
            // Try standard textarea response fields
            var fields = [
                document.getElementById('h-captcha-response'),
                document.querySelector('textarea[name="h-captcha-response"]'),
                document.querySelector('[name="h-captcha-response"]'),
                document.getElementById('g-recaptcha-response'),
                document.querySelector('[name="g-recaptcha-response"]'),
            ];
            var injected = 0;
            for (var f of fields) {{
                if (f) {{
                    f.style.display = 'block';
                    f.value = '{token}';
                    injected++;
                }}
            }}

            // Fire hCaptcha callback if available
            if (window.hcaptcha) {{
                try {{ window.hcaptcha.setResponse('{token}'); }} catch(e) {{}}
            }}

            // Find and call the widget callback
            if (window.hcaptchaOnLoad) {{
                try {{ window.hcaptchaOnLoad(); }} catch(e) {{}}
            }}

            return 'Injected into ' + injected + ' fields';
        }})()
    """
    result = page.evaluate(js)
    print(f"  [inject] {result}")


def inject_turnstile_token(page, token: str):
    """
    Inject a solved Cloudflare Turnstile token into the page.
    """
    js = f"""
        (function() {{
            var injected = 0;
            // Standard cf-turnstile-response field
            var fields = [
                document.querySelector('[name="cf-turnstile-response"]'),
                document.querySelector('input[name="cf-turnstile-response"]'),
            ];
            for (var f of fields) {{
                if (f) {{
                    f.value = '{token}';
                    injected++;
                }}
            }}
            // Turnstile widget callback
            if (window.turnstile) {{
                try {{ window.turnstile.reset(); }} catch(e) {{}}
            }}
            return 'Injected into ' + injected + ' turnstile fields';
        }})()
    """
    result = page.evaluate(js)
    print(f"  [inject turnstile] {result}")
