"""Configure the REAL Telegram bot's webhook for one environment (staging or production).

    uv run --project apps/api python scripts/telegram_setup_webhook.py info
    uv run --project apps/api python scripts/telegram_setup_webhook.py set --url https://api.example.com/api/v1/integrations/telegram/webhook
    uv run --project apps/api python scripts/telegram_setup_webhook.py delete

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET from the environment (or apps/api/.env). Never prints
either value. `set` registers only the update types TermRail handles and the secret Telegram must echo in
X-Telegram-Bot-Api-Secret-Token. It does not send any message to anyone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.core.config import get_settings
from app.integrations.telegram.schemas import ALLOWED_UPDATES

API = "https://api.telegram.org"


def call(token: str, method: str, **params: object) -> dict:
    r = httpx.post(f"{API}/bot{token}/{method}", json=params or None, timeout=30)
    data = r.json()
    if not data.get("ok"):
        # Telegram's description never contains the token; print only that.
        sys.exit(f"{method} failed: {data.get('description', r.status_code)}")
    return data["result"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["info", "set", "delete"])
    ap.add_argument("--url", help="public HTTPS URL of /api/v1/integrations/telegram/webhook")
    args = ap.parse_args()
    s = get_settings()
    if not s.telegram_bot_token:
        sys.exit("TELEGRAM_BOT_TOKEN is not set")
    token = s.telegram_bot_token

    me = call(token, "getMe")
    print(f"bot: @{me.get('username')} (id {me.get('id')}), business bot: {me.get('can_connect_to_business', 'unknown')}")
    if s.telegram_bot_username and me.get("username") != s.telegram_bot_username:
        print(f"WARNING: TELEGRAM_BOT_USERNAME={s.telegram_bot_username} does not match this token's bot")
    if me.get("can_connect_to_business") is False:
        print("WARNING: enable Business Mode for this bot in @BotFather before users can connect it")

    if args.action == "set":
        if not args.url or not args.url.startswith("https://"):
            sys.exit("--url must be an https:// URL")
        if not s.telegram_webhook_secret:
            sys.exit("TELEGRAM_WEBHOOK_SECRET is not set")
        call(
            token,
            "setWebhook",
            url=args.url,
            secret_token=s.telegram_webhook_secret,
            allowed_updates=ALLOWED_UPDATES,
            max_connections=10,
        )
        print("webhook set")
    elif args.action == "delete":
        call(token, "deleteWebhook")
        print("webhook deleted")

    info = call(token, "getWebhookInfo")
    print(f"webhook url: {info.get('url') or '(none)'}")
    print(f"pending updates: {info.get('pending_update_count')}  allowed: {info.get('allowed_updates')}")
    if info.get("last_error_message"):
        print(f"last error: {info.get('last_error_message')}")


if __name__ == "__main__":
    main()
