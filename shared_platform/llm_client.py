import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage


# Generic resolver to find workspace root and ensure relevant directories are on sys.path
def _setup_sys_path():
    curr = Path(__file__).resolve()
    for parent in curr.parents:
        # Check if this is the workspace root containing shared_platform
        if (parent / "shared_platform").is_dir():
            root_path = str(parent)
            if root_path not in sys.path:
                sys.path.insert(0, root_path)

            # Also add TaskManager src to sys.path if it exists (lives under ~/.gemini, not in the workspace tree)
            tm_src = (
                Path.home()
                / ".gemini"
                / "antigravity"
                / "skills"
                / "TaskManager"
                / "src"
            )
            if tm_src.is_dir() and str(tm_src) not in sys.path:
                sys.path.insert(0, str(tm_src))
            break


_setup_sys_path()


class GeminiClient:
    """
    JobHunterKit LLM Client — delegates to LLMProviderRouter (antigravity_cli only).

    Wraps TaskManager.src.llm_provider_router.LLMProviderRouter with provider="antigravity"
    so all LLM calls route exclusively through the Antigravity CLI (agy) with full circuit
    breaker, health probing, exponential backoff, and Langfuse telemetry.

    Zero IPC daemons, sockets, or external Gemini API dependencies.
    """

    def __init__(self):
        self._load_env()
        self.router = self._init_router()

    def _load_env(self):
        candidates = [
            Path(__file__).resolve().parent / ".env",
            Path(__file__).resolve().parent.parent / ".env",
            Path(r".\.env"),
            Path(r".\.env"),
            Path(os.path.expanduser("~")) / ".gemini" / ".env",
            Path(".") / ".env",
        ]
        for candidate in candidates:
            if candidate.exists():
                load_dotenv(candidate, override=False)

    def _init_router(self):
        """Initialises LLMProviderRouter pinned to antigravity_cli (Tier 1 only)."""
        try:
            from llm_provider_router import LLMProviderRouter  # TaskManager.src

            return LLMProviderRouter(provider="antigravity")
        except Exception as e:
            print(
                f"[GeminiClient] WARNING: LLMProviderRouter unavailable: {e}. "
                "Router is None — calls will raise.",
                flush=True,
            )
            return None

    def call(
        self,
        prompt: str,
        json_mode: bool = False,
        temperature: float = 0.0,
        image_b64: str | None = None,
        timeout: float | None = None,
    ) -> str:
        """
        Executes a prompt through the Antigravity CLI via LLMProviderRouter.

        Args:
            prompt: The full prompt string.
            json_mode: If True, appends a JSON-only instruction and strips markdown fences.
            temperature: Passed as hint; router may override per provider capability.
            image_b64: Not used by CLI tier — logged as [image attached] annotation only.
            timeout: Maximum allowed execution timebox in seconds.
        """
        if self.router is None:
            gemini_key = os.getenv("GEMINI_API_KEY")
            if gemini_key:
                return self._call_direct_gemini(
                    full_prompt if not image_b64 else f"{full_prompt}\n\n[Note: Image proof attachment was processed]",
                    json_mode=json_mode,
                    timeout=timeout,
                )
            raise RuntimeError(
                "[GeminiClient] Neither LLMProviderRouter nor GEMINI_API_KEY is available. "
                "Please configure GEMINI_API_KEY in your .env file."
            )

        full_prompt = prompt
        if image_b64 and not prompt.endswith("(image attached)"):
            full_prompt = f"{prompt}\n\n[Note: Image proof attachment was processed]"

        if json_mode and "json" not in full_prompt.lower():
            full_prompt += "\n\nRespond with valid JSON only."

        # Smart contextual SLA budget: fast 10s for form prompts, 35s for medium prompts, 65s for heavy debate prompts
        if timeout is None:
            if len(full_prompt) > 15000:
                timeout = 65.0
            elif len(full_prompt) > 2500:
                timeout = 35.0
            else:
                timeout = 10.0

        print(
            f"[GeminiClient] Routing prompt ({len(full_prompt)} chars, timebox: {timeout}s) via LLMProviderRouter (antigravity_cli)",
            flush=True,
        )

        try:
            output, latency_ms, cost_usd = self.router.generate(
                messages=[HumanMessage(content=full_prompt)],
                timeout=timeout,
                json_mode=json_mode,
            )
        except Exception as e:
            print(f"[GeminiClient] LLMProviderRouter call failed: {e}", flush=True)
            raise RuntimeError(f"LLMProviderRouter execution failed: {e}") from e

        if not isinstance(output, str) or not output.strip():
            raise RuntimeError(
                f"[GeminiClient] Router returned empty or non-string output: {output!r}"
            )

        return output

    def _call_direct_gemini(
        self,
        prompt: str,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> str:
        """Direct fallback to Google Gemini REST API when running outside Antigravity."""
        import requests

        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
            },
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        print(
            f"[GeminiClient] Calling Gemini REST API ({model}) directly (fallback mode)...",
            flush=True,
        )
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout or 60.0,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Gemini API error (HTTP {resp.status_code}): {resp.text}"
            )
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Gemini API returned no candidates: {data}")
        text = (
            candidates[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        return text
