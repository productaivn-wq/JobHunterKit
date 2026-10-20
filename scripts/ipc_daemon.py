"""
Direct IPC Daemon for JobHunterKit.
Listens for request files in the ipc directory and responds by routing LLM calls
through the Antigravity CLI (via LLMProviderRouter, antigravity_cli tier).
Also polls Telegram every 5s for /stop and /start commands that gate the pipeline.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

# Load env file from the JobHunterKit directory
load_dotenv(Path(__file__).parent.parent / ".env")

# Add project root for shared_platform imports
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared_platform import pipeline_state as _pipeline_state
from shared_platform.notify import send_telegram as _send_telegram


def set_conversation_parent(conv_id: str, parent_id: str) -> bool:
    """Updates SQLite trajectory metadata to link a subagent conversation to its parent orchestrator."""
    import re
    import sqlite3

    db_path = (
        Path(os.path.expanduser("~"))
        / ".gemini"
        / "antigravity"
        / "conversations"
        / f"{conv_id}.db"
    )

    # Wait up to 2 seconds for the database file to be created
    for _ in range(20):
        if db_path.exists():
            break
        time.sleep(0.1)

    if not db_path.exists():
        return False

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM trajectory_metadata_blob WHERE id='main';")
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False

        data = bytearray(row[0])
        root_matches = list(re.finditer(rb"\x32\x24[0-9a-fA-F\-]{36}", data))
        if not root_matches:
            conn.close()
            return False

        root_idx = root_matches[0].start()

        parent_matches = list(re.finditer(rb"\x2a\x24[0-9a-fA-F\-]{36}", data))
        if parent_matches:
            parent_idx = parent_matches[0].start()
            parent_field = b"\x2a\x24" + parent_id.encode("ascii")
            data[parent_idx : parent_idx + len(parent_matches[0].group())] = (
                parent_field
            )
            root_matches = list(re.finditer(rb"\x32\x24[0-9a-fA-F\-]{36}", data))
            if root_matches:
                root_idx = root_matches[0].start()
                root_field = b"\x32\x24" + parent_id.encode("ascii")
                data[root_idx : root_idx + len(root_matches[0].group())] = root_field
        else:
            parent_field = b"\x2a\x24" + parent_id.encode("ascii")
            root_field = b"\x32\x24" + parent_id.encode("ascii")
            new_data = (
                data[:root_idx]
                + parent_field
                + root_field
                + data[root_idx + len(root_matches[0].group()) :]
            )
            data = bytearray(new_data)

        cursor.execute(
            "UPDATE trajectory_metadata_blob SET data=? WHERE id='main';",
            (bytes(data),),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as exc:
        print(f"[IPC DEBUG] Failed setting conversation parent: {exc}", flush=True)
        return False


IPC_DIR = _project_root / "ipc"

try:
    from ipc_utils import (
        acquire_cross_process_lock,
        get_visual_agent_response,
        release_cross_process_lock,
    )
except ImportError:
    from scripts.ipc_utils import (
        acquire_cross_process_lock,
        get_visual_agent_response,
        release_cross_process_lock,
    )

# Cooldown database: tracks expiration timestamps
# key: (model_or_service, credential), value: float (timestamp when it is off cooldown)
cooldowns = {}
cooldowns_lock = threading.Lock()


def get_cooldown_expiry(model_or_service: str, credential: str) -> float:
    """Retrieves the unix timestamp when the given provider credential exits cooldown."""
    with cooldowns_lock:
        return cooldowns.get((model_or_service, credential), 0.0)


def set_cooldown(model_or_service: str, credential: str, duration: float) -> None:
    """Places a model provider or credential on temporary cooldown for the specified duration."""
    with cooldowns_lock:
        cooldowns[(model_or_service, credential)] = time.time() + duration


def call_claude_cli(prompt: str, req_uuid: str) -> str:
    """Invokes Claude CLI to obtain response."""
    now = time.time()
    if now < get_cooldown_expiry("cli", "claude"):
        return ""

    scratch_dir = Path(__file__).resolve().parent.parent / "scratch"
    temp_prompt_file = scratch_dir / f"prompt_{req_uuid}.txt"
    lock_file = scratch_dir / "cli_rate_limit.lock"
    acquire_cross_process_lock(lock_file)
    try:
        with open(temp_prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)

        print("[DAEMON] Invoking Claude CLI via print mode...", flush=True)
        cmd = f'cmd.exe /c "claude --safe-mode --tools "" --print < "{temp_prompt_file.resolve()}""'
        start_t = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        elapsed = time.time() - start_t

        if result.returncode == 0 and result.stdout:
            stdout_clean = result.stdout.strip()
            # Remove Claude's standard stdin warning if present
            warning_prefix = "Warning: no stdin data received in 3s, proceeding without it. If piping from a slow command, redirect stdin explicitly: < /dev/null to skip, or wait longer."
            if warning_prefix in stdout_clean:
                stdout_clean = stdout_clean.replace(warning_prefix, "").strip()

            if stdout_clean:
                print(f"[DAEMON] Claude CLI succeeded in {elapsed:.2f}s.", flush=True)
                return stdout_clean

        print(
            f"[DAEMON WARNING] Claude CLI failed or returned empty. code={result.returncode}, stderr={result.stderr}",
            flush=True,
        )
        # Put Claude CLI on cooldown to prevent repeated slow spawning
        set_cooldown("cli", "claude", 60)
    except Exception as e_claude:
        print(f"[DAEMON ERROR] Claude CLI invocation failed: {e_claude}", flush=True)
        set_cooldown("cli", "claude", 60)
    finally:
        release_cross_process_lock(lock_file)
        try:
            if temp_prompt_file and temp_prompt_file.exists():
                temp_prompt_file.unlink()
        except Exception:
            pass
    return ""


def call_antigravity_cli(prompt: str, req_uuid: str, json_mode: bool = False) -> str:
    """Invokes Antigravity (agentapi) CLI to obtain response."""
    now = time.time()
    if now < get_cooldown_expiry("cli", "antigravity"):
        return ""

    scratch_dir = Path(__file__).resolve().parent.parent / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    temp_prompt_file_api = scratch_dir / f"prompt_{req_uuid}_api.txt"
    lock_file = scratch_dir / "cli_rate_limit.lock"
    acquire_cross_process_lock(lock_file)
    try:
        print("[DAEMON] Invoking Antigravity CLI (agentapi)...", flush=True)
        roaming_bat = (
            Path(os.path.expanduser("~"))
            / "AppData"
            / "Roaming"
            / "Antigravity"
            / "bin"
            / "agentapi.bat"
        )
        lang_server_path = (
            Path(os.path.expanduser("~"))
            / "AppData"
            / "Local"
            / "Programs"
            / "Antigravity"
            / "resources"
            / "bin"
            / "language_server.exe"
        )
        if roaming_bat.exists():
            cli_base_args = [str(roaming_bat)]
        elif lang_server_path.exists():
            cli_base_args = [str(lang_server_path), "agentapi"]
        else:
            cli_base_args = [
                str(
                    Path(os.path.expanduser("~"))
                    / ".gemini"
                    / "antigravity"
                    / "bin"
                    / "agentapi.bat"
                )
            ]

        # Instruction to suppress unnecessary tool calling and task tracking
        instruction = "\n\nCRITICAL: Do NOT call any tools except view_file to read the prompt file. You must respond directly in text/JSON as requested. Output the final response directly."

        start_t = time.time()
        conv_id = None

        # 1. Write the prompt content to a temp file (completely avoids CLI length limits)
        with open(temp_prompt_file_api, "w", encoding="utf-8") as pf:
            pf.write(prompt)

        # 2. Instruct the agent to read the file using view_file
        short_prompt = (
            f"Please read the agent prompt from the file: {temp_prompt_file_api.as_posix()} using the view_file tool. "
            f"Process the request described in that file and respond directly. "
            f"{instruction}"
        )

        print(
            "[DAEMON] Sending file-backed prompt via new-conversation command...",
            flush=True,
        )
        cmd_args = cli_base_args + ["new-conversation", short_prompt]
        result = subprocess.run(
            cmd_args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode == 0 and result.stdout:
            try:
                resp_json = json.loads(result.stdout)
                conv_id = (
                    resp_json.get("response", {})
                    .get("newConversation", {})
                    .get("conversationId")
                )
            except Exception:
                print(
                    f"[DAEMON WARNING] Failed to parse new-conversation output: {result.stdout}",
                    flush=True,
                )
        else:
            print(
                f"[DAEMON WARNING] agentapi new-conversation failed. code={result.returncode}, stdout={result.stdout}, stderr={result.stderr}",
                flush=True,
            )

        expected_step_idx = 2

        if conv_id:
            parent_id = os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
            if not parent_id:
                try:
                    parent_file = (
                        Path(os.path.expanduser("~"))
                        / ".gemini"
                        / "antigravity"
                        / "active_parent_conversation.txt"
                    )
                    if parent_file.exists():
                        with open(parent_file, encoding="utf-8") as f:
                            parent_id = f.read().strip()
                except Exception as pe:
                    print(
                        f"[DAEMON WARNING] Error reading parent file: {pe}", flush=True
                    )
            if parent_id:
                try:
                    success = set_conversation_parent(conv_id, parent_id)
                    if success:
                        print(
                            f"[DAEMON] Nested new conversation {conv_id} under parent {parent_id}",
                            flush=True,
                        )
                    else:
                        print(
                            f"[DAEMON WARNING] Failed to nest new conversation {conv_id} under parent {parent_id}",
                            flush=True,
                        )
                except Exception as ne:
                    print(
                        f"[DAEMON WARNING] Error nesting conversation: {ne}", flush=True
                    )

            # Poll transcript
            logs_dir = (
                Path(os.path.expanduser("~"))
                / ".gemini"
                / "antigravity"
                / "brain"
                / conv_id
                / ".system_generated"
                / "logs"
            )
            transcript_path = logs_dir / "transcript_full.jsonl"
            if not transcript_path.exists():
                transcript_path = logs_dir / "transcript.jsonl"
            poll_start = time.time()
            timeout = 180
            while time.time() - poll_start < timeout:
                if transcript_path.exists():
                    try:
                        with open(transcript_path, encoding="utf-8") as tf:
                            lines = tf.readlines()

                        for line in reversed(lines):
                            try:
                                step = json.loads(line)
                                if (
                                    step.get("type") == "PLANNER_RESPONSE"
                                    and step.get("step_index") >= expected_step_idx
                                ):
                                    tool_calls = step.get("tool_calls")
                                    if (
                                        not tool_calls
                                    ):  # Only accept tool-free responses
                                        content = step.get("content", "").strip()
                                        if content:
                                            if json_mode:
                                                clean_content = content
                                                if clean_content.startswith("```"):
                                                    lines_c = clean_content.splitlines()
                                                    if len(lines_c) >= 2:
                                                        clean_content = "\n".join(
                                                            lines_c[1:-1]
                                                        ).strip()
                                                try:
                                                    json.loads(clean_content)
                                                    elapsed = time.time() - start_t
                                                    print(
                                                        f"[DAEMON] Antigravity CLI succeeded (JSON mode) in {elapsed:.2f}s.",
                                                        flush=True,
                                                    )
                                                    return clean_content
                                                except:
                                                    pass
                                            else:
                                                elapsed = time.time() - start_t
                                                print(
                                                    f"[DAEMON] Antigravity CLI succeeded in {elapsed:.2f}s.",
                                                    flush=True,
                                                )
                                                return content
                            except Exception:
                                pass
                    except Exception:
                        pass
                time.sleep(1.0)
            print(
                f"[DAEMON ERROR] Polling Antigravity conversation {conv_id} timed out.",
                flush=True,
            )

        # If we failed or timed out, put Antigravity CLI on cooldown
        set_cooldown("cli", "antigravity", 120)
    except Exception as e_agt:
        print(f"[DAEMON ERROR] Antigravity CLI failed: {e_agt}", flush=True)
        set_cooldown("cli", "antigravity", 120)
    finally:
        release_cross_process_lock(lock_file)
        try:
            if temp_prompt_file_api and temp_prompt_file_api.exists():
                temp_prompt_file_api.unlink()
        except Exception:
            pass
    return ""


def is_antigravity_ls_running() -> bool:
    import socket

    addr = os.getenv("ANTIGRAVITY_LS_ADDRESS", "localhost:56105")
    if not addr:
        return False
    try:
        host, port_str = addr.split(":", 1)
        port = int(port_str)
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except Exception:
        return False


def call_llm_router(prompt: str, json_mode: bool = False, image_b64: str = None) -> str:
    """
    Routes an LLM request through LLMProviderRouter (antigravity_cli tier only).
    Replaces the legacy call_gemini_api() direct-API approach.
    Circuit breakers, health probing, and exponential backoff are handled by the router.
    """
    try:
        from shared_platform.llm_client import GeminiClient

        client = GeminiClient()
        return client.call(prompt, json_mode=json_mode, image_b64=image_b64)
    except Exception as e:
        print(f"[DAEMON] LLMProviderRouter call failed: {e}", flush=True)
        return ""


executor = ThreadPoolExecutor(max_workers=60)

# ------------------------------------------------------------------
# Telegram /stop / /start command polling
# ------------------------------------------------------------------
TELEGRAM_POLL_INTERVAL = 5.0
_last_telegram_poll: float = 0.0


def poll_telegram_commands() -> None:
    """
    Short-polls Telegram getUpdates (timeout=0, non-blocking) for /stop and /start
    commands from the configured chat. Updates pipeline_state in Postgres and sends
    an acknowledgement message back to the user.

    Uses short-poll (timeout=0) NOT long-poll — a blocking long-poll would stall
    the daemon's IPC-serving responsiveness.
    """
    global _last_telegram_poll
    now = time.time()
    if now - _last_telegram_poll < TELEGRAM_POLL_INTERVAL:
        return
    _last_telegram_poll = now

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    if not bot_token or not chat_id:
        return

    try:
        offset = _pipeline_state.get_last_update_id() + 1
        url = (
            f"https://api.telegram.org/bot{bot_token}/getUpdates"
            f"?offset={offset}&timeout=0&allowed_updates=message"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[DAEMON WARNING] Telegram getUpdates failed: {e}", flush=True)
        return

    if not data.get("ok"):
        return

    max_update_id = offset - 1
    for update in data.get("result", []):
        uid = update.get("update_id", 0)
        if uid > max_update_id:
            max_update_id = uid

        msg = update.get("message", {})
        # Only act on messages from the authorised chat
        if str(msg.get("chat", {}).get("id", "")) != chat_id:
            continue

        text = (msg.get("text") or "").strip().lower()
        try:
            if text.startswith("/stop") or text.startswith("/pause"):
                _pipeline_state.set_paused(True, actor="telegram:/stop")
                _send_telegram(
                    "⏸ <b>Pipeline paused.</b>\n"
                    "Any job currently in-flight will finish. "
                    "New jobs will not be claimed until you send /start or /resume."
                )
                print(f"[DAEMON] Pipeline paused via Telegram {text}.", flush=True)
            elif text.startswith("/start") or text.startswith("/resume"):
                _pipeline_state.set_paused(False, actor="telegram:/start")
                _send_telegram(
                    "▶️ <b>Pipeline resumed.</b>\n"
                    "JobHunterKit will pick up pending jobs on the next queue check."
                )
                print(f"[DAEMON] Pipeline resumed via Telegram {text}.", flush=True)
        except Exception as cmd_err:
            print(
                f"[DAEMON WARNING] Telegram command handling failed: {cmd_err}",
                flush=True,
            )

    if max_update_id >= offset:
        try:
            _pipeline_state.set_last_update_id(max_update_id)
        except Exception as e:
            print(f"[DAEMON WARNING] Failed to persist last_update_id: {e}", flush=True)


def process_request_data(req_name: str, data: dict):
    if req_name == "request.json":
        resp_file = IPC_DIR / "response.json"
    else:
        req_id = req_name.replace("request_", "").replace(".json", "")
        resp_file = IPC_DIR / f"response_{req_id}.json"

    if not isinstance(data, dict):
        print(
            f"[DAEMON ERROR] Invalid request data format for {req_name}: expected dict, got {type(data)}",
            flush=True,
        )
        return

    prompt = data.get("prompt", "")
    json_mode = data.get("json_mode", False)
    image_b64 = data.get("image_b64", None)

    if prompt:
        print(
            f"[DAEMON] Processing request {req_name} (json_mode={json_mode}, image_b64={bool(image_b64)})...",
            flush=True,
        )
        start_time = time.time()

        local_resp = None
        if json_mode:
            try:
                local_resp = get_visual_agent_response(
                    prompt, req_id if req_name != "request.json" else "main"
                )
            except Exception as le:
                print(f"[DAEMON WARNING] Local responder error: {le}", flush=True)

        if local_resp and isinstance(local_resp, dict) and "response" in local_resp:
            inner_res = local_resp["response"]
            if isinstance(inner_res, dict):
                response_text = json.dumps(inner_res, ensure_ascii=False)
            else:
                response_text = str(inner_res)
            print("[DAEMON] Handled request locally using rules.", flush=True)
        else:
            response_text = call_llm_router(prompt, json_mode, image_b64)

        if response_text:
            payload = {"response": response_text}
            try:
                with open(resp_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                elapsed = time.time() - start_time
                print(
                    f"[DAEMON] Successfully wrote response to {resp_file.name} in {elapsed:.2f}s.",
                    flush=True,
                )
            except Exception as e:
                print(
                    f"[DAEMON ERROR] Failed to write response to {resp_file.name}: {e}",
                    flush=True,
                )
        else:
            # Write an explicit error sentinel file so caller fails fast
            error_payload = {
                "error": "DAEMON_LLM_FAILED",
                "detail": "LLMProviderRouter (antigravity_cli) failed to produce a response. Check agy CLI health and router circuit breaker state.",
            }
            try:
                with open(resp_file, "w", encoding="utf-8") as f:
                    json.dump(error_payload, f)
                print(
                    f"[DAEMON ERROR] Wrote error sentinel to {resp_file.name} — caller will fail fast.",
                    flush=True,
                )
            except Exception as write_err:
                print(
                    f"[DAEMON ERROR] Failed to write error sentinel {resp_file.name}: {write_err}",
                    flush=True,
                )


_daemon_port_lock = None


def acquire_daemon_single_instance_lock() -> bool:
    global _daemon_port_lock
    import socket

    try:
        _daemon_port_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _daemon_port_lock.bind(("127.0.0.1", 56200))
        return True
    except OSError:
        _daemon_port_lock = None
        return False


def run_daemon_loop():
    try:
        IPC_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[DAEMON] Direct IPC Daemon started. Watching {IPC_DIR}...")
        while True:
            try:
                # Write heartbeat
                heartbeat_file = IPC_DIR / "daemon_heartbeat.json"
                try:
                    with open(heartbeat_file, "w", encoding="utf-8") as f:
                        json.dump({"timestamp": time.time(), "pid": os.getpid()}, f)
                except Exception:
                    pass

                # Poll Telegram for /stop / /start commands (every 5s, non-blocking)
                try:
                    poll_telegram_commands()
                except Exception as tg_err:
                    print(
                        f"[DAEMON WARNING] poll_telegram_commands raised: {tg_err}",
                        flush=True,
                    )

                req_files = list(IPC_DIR.glob("request_*.json"))
                legacy_req = IPC_DIR / "request.json"
                if legacy_req.exists():
                    req_files.append(legacy_req)

                for req_file in req_files:
                    try:
                        time.sleep(0.1)
                        with open(req_file, encoding="utf-8") as f:
                            data = json.load(f)
                        req_file.unlink()
                    except (FileNotFoundError, PermissionError):
                        continue
                    except json.JSONDecodeError:
                        continue

                    executor.submit(process_request_data, req_file.name, data)

                time.sleep(0.5)
            except KeyboardInterrupt:
                print("[DAEMON] Stopping daemon.")
                break
            except Exception as e:
                print(f"[DAEMON EXCEPTION] {e}", flush=True)
                time.sleep(2)
    except BaseException as e:
        import traceback

        print(
            f"[DAEMON CRITICAL ERROR] Main thread crashed: {e}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if not acquire_daemon_single_instance_lock():
        print(
            "[DAEMON ERROR] Another instance of the IPC Daemon is already running. Exiting.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(0)
    run_daemon_loop()
