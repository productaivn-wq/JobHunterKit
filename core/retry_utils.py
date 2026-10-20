"""Retry utilities and unified LLM caller for JobHunterKit."""

import functools
import sys
import time
from pathlib import Path


def retry_llm(func):
    """Fast-fail backoff decorator for LLM calls (max 2 attempts, 1s backoff)."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        max_attempts = kwargs.pop("max_retries", 2)
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == max_attempts - 1:
                    print(f"[LLM RETRY] Final attempt {attempt + 1}/{max_attempts} failed: {e}.")
                    raise
                backoff_time = 1.0
                print(
                    f"[LLM RETRY] Attempt {attempt + 1}/{max_attempts} failed: {e}. Retrying in {backoff_time}s..."
                )
                time.sleep(backoff_time)

    return wrapper


@retry_llm
def call_llm_unified(
    prompt: str,
    api_key: str = "",
    json_mode: bool = False,
    timeout: float | None = None,
) -> str:
    """Unified LLM call via Antigravity Native CLI (agy.exe) with fast-fail retry and timebox."""
    kit_root = Path(__file__).resolve().parent.parent
    if str(kit_root) not in sys.path:
        sys.path.insert(0, str(kit_root))

    from shared_platform.llm_client import GeminiClient

    client = GeminiClient()
    return client.call(prompt, json_mode=json_mode, timeout=timeout)


# Alias for backward compatibility
_call_llm_unified = call_llm_unified
