"""
Telemetry and LangFuse integration layer for JobHunterKit.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def is_langfuse_enabled() -> bool:
    return os.getenv("LANGFUSE_ENABLED", "false").lower() in ("true", "1")


def score_trace(
    trace_id: str, name: str, value: float, comment: str | None = None
) -> None:
    """Logs a numerical evaluation score to the active trace in Langfuse or local logger."""
    if not trace_id:
        return
    if is_langfuse_enabled():
        try:
            from langfuse import Langfuse

            public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
            secret_key = os.getenv("LANGFUSE_SECRET_KEY")
            host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
            if public_key and secret_key:
                lf = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
                lf.score(trace_id=trace_id, name=name, value=value, comment=comment)
                return
        except Exception as e:
            logger.debug(f"[Telemetry] Langfuse score logging error: {e}")

    logger.info(
        f"[Telemetry Score] trace={trace_id} name={name} val={value} comment={comment}"
    )


def log_metric(name: str, value: float, metadata: dict[str, Any] | None = None) -> None:
    """Logs a custom metric."""
    logger.info(f"[Metric] {name}: {value} (meta={metadata})")
