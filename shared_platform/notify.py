"""
Shared Notification Platform Layer for JobHunterKit.
Provides unified notification channels like Telegram without external library dependencies.
"""

import json
import os
import urllib.parse
import urllib.request


def send_telegram(text: str) -> bool:
    """
    Sends a message via the Telegram Bot API using urllib.
    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment variables.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print(
            "[WARNING] Telegram credentials missing in environment. Alert suppressed."
        )
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with urllib.request.urlopen(req, timeout=10) as response:
            res = response.read().decode("utf-8")
            res_json = json.loads(res)
            return res_json.get("ok", False)
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram message: {e}")
        return False


def send_telegram_file(filepath: str, caption: str = "") -> bool:
    """
    Sends a document file via Telegram Bot API using multipart/form-data.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("[WARNING] Telegram credentials missing in environment.")
        return False

    if not os.path.exists(filepath):
        print(f"[ERROR] File does not exist: {filepath}")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    boundary = "------------------------jobhunterboundary12345"

    try:
        with open(filepath, "rb") as f:
            file_data = f.read()

        filename = os.path.basename(filepath)
        body = bytearray()

        # chat_id field
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode()
        )

        # caption field
        if caption:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode()
            )

        # document field
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode()
        )
        body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        body.extend(file_data)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(url, data=bytes(body), method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

        with urllib.request.urlopen(req, timeout=30) as response:
            res = response.read().decode("utf-8")
            res_json = json.loads(res)
            return res_json.get("ok", False)
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram file: {e}")
        return False


def ask_telegram_question(
    question: str, suggestion: str = "", timeout: int = 60
) -> str:
    """
    Sends a prompt/question to Telegram and polls getUpdates for an answer.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        return None

    prompt_text = f"❓ <b>Interactive Prompt:</b>\n{question}"
    if suggestion:
        prompt_text += f"\n<i>Suggestion: {suggestion}</i>"
    prompt_text += "\n\nReply with <code>/ans &lt;your answer&gt;</code>"

    if not send_telegram(prompt_text):
        return None

    import time

    start_time = time.time()
    last_update_id = 0

    # Get baseline update_id
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode("utf-8"))
            if res.get("ok") and res.get("result"):
                last_update_id = res["result"][-1]["update_id"]
    except Exception:
        pass

    while time.time() - start_time < timeout:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset={last_update_id + 1}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as response:
                res = json.loads(response.read().decode("utf-8"))
                if res.get("ok"):
                    for update in res.get("result", []):
                        last_update_id = max(last_update_id, update["update_id"])
                        msg = update.get("message", {})
                        if str(msg.get("chat", {}).get("id")) == str(chat_id):
                            text = msg.get("text", "").strip()
                            if text.startswith("/ans"):
                                ans = text[4:].strip()
                                send_telegram(f"✅ Received answer: <i>{ans}</i>")
                                return ans
        except Exception:
            pass
        time.sleep(2)

    return None
