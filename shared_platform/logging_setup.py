"""
Structured Logging & Flow Entrypoint Platform Layer for JobHunterKit.
Provides decorators and helpers for structured flow execution, stdout redirection,
and JSON event logging.
"""

import datetime
import functools
import json
import os
import sys
import traceback


class TimestampedStream:
    """Wraps a stream to prepend a timestamp [YYYY-MM-DD HH:MM:SS] to every line."""

    def __init__(self, stream):
        self.stream = stream
        self._at_line_start = True

    def write(self, data):
        if not data:
            return
        lines = data.splitlines(keepends=True)
        for line in lines:
            if not line:
                continue
            if self._at_line_start and line.strip():
                # Avoid double timestamps if the line already starts with a timestamp or JSON event
                if not (line.startswith("[202") or line.startswith('{"timestamp"') or line.startswith("=== Flow")):
                    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.stream.write(f"[{now_str}] ")
            self.stream.write(line)
            self._at_line_start = line.endswith("\n")

    def flush(self):
        if hasattr(self.stream, "flush"):
            self.stream.flush()

    def reconfigure(self, **kwargs):
        if hasattr(self.stream, "reconfigure"):
            self.stream.reconfigure(**kwargs)

    def isatty(self):
        return getattr(self.stream, "isatty", lambda: False)()

    def __getattr__(self, name):
        return getattr(self.stream, name)


class TeeStream:
    """Tees stream writes to multiple destinations (e.g. console stdout and file)."""

    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, data):
        if not data:
            return
        for s in self.streams:
            try:
                s.write(data)
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                if hasattr(s, "flush"):
                    s.flush()
            except Exception:
                pass

    def reconfigure(self, **kwargs):
        for s in self.streams:
            try:
                if hasattr(s, "reconfigure"):
                    s.reconfigure(**kwargs)
            except Exception:
                pass

    def isatty(self):
        return any(getattr(s, "isatty", lambda: False)() for s in self.streams)

    def __getattr__(self, name):
        if self.streams:
            return getattr(self.streams[0], name)
        raise AttributeError(name)


def flow_entrypoint(flow_name: str):
    """
    Decorator that encapsulates a flow script's execution:
    - Enriches all stream output with real-time timestamps [YYYY-MM-DD HH:MM:SS].
    - Flushes output immediately using line-buffering.
    - Captures, logs, and formats exceptions into structured JSON events.
    - Tees output to both the console (IDE output window) and logs/<flow_name>.log.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            original_stdout = sys.stdout
            original_stderr = sys.stderr

            # Resolve log file path under project root logs/ folder
            script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            logs_dir = os.path.join(script_dir, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            log_file = os.path.join(logs_dir, f"{flow_name}.log")

            # Open the log file with line buffering (buffering=1) for immediate writes
            try:
                log_f = open(log_file, "a", encoding="utf-8", buffering=1)
                stdout_target = TeeStream(original_stdout, log_f)
                stderr_target = TeeStream(original_stderr, log_f)
            except Exception:
                log_f = None
                stdout_target = original_stdout
                stderr_target = original_stderr

            sys.stdout = TimestampedStream(stdout_target)
            sys.stderr = TimestampedStream(stderr_target)

            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_event("info", f"Starting flow: {flow_name}", timestamp=now_str)

            exit_code = 0
            exit_error = None

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                exit_code = 1
                exit_error = str(e)
                log_event(
                    "error",
                    f"Flow {flow_name} crashed: {e}",
                    traceback=traceback.format_exc(),
                    timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                raise e
            finally:
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if exit_code != 0:
                    log_event(
                        "fatal",
                        f"Flow {flow_name} finished with failure (exit code {exit_code})",
                        error=exit_error,
                        timestamp=now_str,
                    )
                else:
                    log_event(
                        "info",
                        f"Flow {flow_name} finished successfully",
                        timestamp=now_str,
                    )

                log_f.close()
                sys.stdout = original_stdout
                sys.stderr = original_stderr

        return wrapper

    return decorator


def log_event(level: str, message: str, **kwargs):
    """Logs a structured JSON event to stdout."""
    event = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "level": level.upper(),
        "message": message,
    }
    event.update(kwargs)
    print(json.dumps(event), flush=True)


def log_checkpoint_event(
    event_type: str,
    node_name: str = "",
    edge_name: str = "",
    use_case_id: str = "",
    function_id: str = "",
    checkpoint_id: str = "",
    state_summary: dict = None,
    duration_ms: float = 0.0,
    **kwargs,
):
    """Emits a structured CHECKPOINT log event."""
    data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "level": "CHECKPOINT",
        "event_type": event_type,
        "node_name": node_name,
        "edge_name": edge_name,
        "use_case_id": use_case_id,
        "function_id": function_id,
        "checkpoint_id": checkpoint_id,
        "duration_ms": duration_ms,
        "state_summary": state_summary or {},
    }
    data.update(kwargs)
    print(json.dumps(data), flush=True)


def log_edge_transition(
    source_node: str,
    target_node: str,
    transition_type: str = "DIRECT",
    edge_name: str = "",
    condition_name: str = "",
    condition: str = "",
    use_case_id: str = "",
    function_id: str = "",
    checkpoint_id: str = "",
    duration_ms: float = 0.0,
    **kwargs,
):
    """Emits a structured EDGE_TRANSITION event."""
    cond = condition or condition_name
    log_checkpoint_event(
        event_type="EDGE_TRANSITION",
        node_name=source_node,
        edge_name=edge_name or f"{source_node}->{target_node}",
        source_node=source_node,
        target_node=target_node,
        transition_type=transition_type,
        condition=cond,
        condition_name=cond,
        use_case_id=use_case_id,
        function_id=function_id,
        checkpoint_id=checkpoint_id,
        duration_ms=duration_ms,
        **kwargs,
    )


def checkpointed_node(
    node_name: str,
    use_case_id: str = "",
    function_id: str = "",
    checkpoint_id: str = "",
):
    """Decorator that wraps a LangGraph node to log lifecycle events."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(state, *args, **kwargs):
            thread_id = state.get("trace_id", "") if isinstance(state, dict) else ""
            import time

            start_t = time.time()
            log_checkpoint_event(
                event_type="NODE_ENTRY",
                node_name=node_name,
                use_case_id=use_case_id,
                function_id=function_id,
                checkpoint_id=checkpoint_id or f"CP-{node_name}-ENTRY",
                thread_id=thread_id,
            )
            try:
                result = func(state, *args, **kwargs)
                duration_ms = (time.time() - start_t) * 1000.0
                log_checkpoint_event(
                    event_type="CHECKPOINT_SAVED",
                    node_name=node_name,
                    use_case_id=use_case_id,
                    function_id=function_id,
                    checkpoint_id=checkpoint_id or f"CP-{node_name}-SAVED",
                    thread_id=thread_id,
                    duration_ms=duration_ms,
                    status="SUCCESS",
                )
                log_checkpoint_event(
                    event_type="NODE_EXIT",
                    node_name=node_name,
                    use_case_id=use_case_id,
                    function_id=function_id,
                    checkpoint_id=checkpoint_id or f"CP-{node_name}-EXIT",
                    thread_id=thread_id,
                    duration_ms=duration_ms,
                )
                return result
            except Exception as e:
                duration_ms = (time.time() - start_t) * 1000.0
                log_checkpoint_event(
                    event_type="NODE_ERROR",
                    node_name=node_name,
                    use_case_id=use_case_id,
                    function_id=function_id,
                    checkpoint_id=checkpoint_id or f"CP-{node_name}-ERR",
                    thread_id=thread_id,
                    duration_ms=duration_ms,
                    status="FAILED",
                    error=str(e),
                )
                raise e

        return wrapper

    return decorator


def checkpointed_function(
    function_id: str = "",
    use_case_id: str = "",
    stage_name: str = "",
    **decorator_kwargs,
):
    """Decorator that marks a function as a traceable, checkpointed operation."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import time

            start_t = time.time()
            log_checkpoint_event(
                event_type="FUNCTION_ENTRY",
                node_name=stage_name or func.__name__,
                function_id=function_id,
                use_case_id=use_case_id,
            )
            result = func(*args, **kwargs)
            duration_ms = (time.time() - start_t) * 1000.0
            log_checkpoint_event(
                event_type="FUNCTION_CHECKPOINT",
                node_name=stage_name or func.__name__,
                function_id=function_id,
                use_case_id=use_case_id,
                duration_ms=duration_ms,
            )
            return result

        return wrapper

    return decorator
