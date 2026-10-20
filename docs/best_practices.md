# JobHunterKit Best Practices

This document outlines proven design patterns, guidelines, and lessons learned from developing and maintaining the `JobHunterKit` automation engine.

---

## 1. Window Management & Focus Prevention

To ensure automated job application processes execute continuously without stealing system focus or interrupting active user typing:

- **Subprocess Creation Flags**: Always invoke background CLI commands, python workers, or other helper scripts in Windows using the `subprocess.CREATE_NO_WINDOW` flag:
  ```python
  import sys
  import subprocess

  creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
  subprocess.run(args, creationflags=creationflags)
  ```
- **Headless Browser Execution**: Ensure Playwright browsers run in headless mode for all automated tasks. Headed browser windows (`headless=False`) must be restricted only to interactive credential setup tasks (e.g. `login_linkedin.py`).

---

## 2. LLM Call Reliability & CLI Routing

- **Direct Binary Calls**: When routing LLM prompts through the Antigravity fallback, invoke the direct executable `language_server.exe` instead of the `agentapi.bat` shell wrapper. Direct invocations via `subprocess.run` on binary files bypass command-line expansion limits and character-escaping corruptions that occur in Windows batch scripts.
- **API Key Rotation**: Configure multiple API keys in the `.env` file separated by commas. The IPC daemon will automatically rotate keys upon receiving rate limit codes (`429`), preventing pipeline failures.
- **Prompt Length Truncation**: Keep request prompts below CLI arguments limits (ideally <7500 characters) when using the CLI fallback, or use file-based arguments where possible.

---

## 3. Database & Concurrency

- **Connection Pool Tuning**: Ensure Supabase PostgreSQL database connections specify schema paths at the protocol connection level (`options="-c search_path=task_manager,public"`). Avoid using post-connection setup commands like `SET search_path`, which can cause connection drops under Supabase transaction-mode pooling (PgBouncer).
- **Graceful Failure Sentinels**: Write error sentinel files (e.g., `{"error": "DAEMON_GEMINI_FAILED"}`) in the IPC directory if all LLM backends fail, allowing calling scraper scripts to exit gracefully immediately instead of hanging for long timeouts.
