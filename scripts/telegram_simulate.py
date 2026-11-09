"""SYNTHETIC Telegram walkthrough against a RUNNING TermRail API (local dev / staging rehearsal only).

    uv run --project apps/api python scripts/telegram_simulate.py --synthetic \
        [--api http://localhost:8000/api/v1] [--lang en|ru]

It plays Telegram's side by POSTing typed Bot API updates to the real webhook (same secret check, same
database, same worker and the REAL configured AI provider). Everything Telegram-side is fictional: the
business connection, the chat and the client. It is NOT evidence that a real Telegram account works --
that requires scripts/telegram_setup_webhook.py with a real bot and a Telegram Business account.

Requires TELEGRAM_WEBHOOK_SECRET in the environment (never printed). Run the server with a short
TELEGRAM_MESSAGE_DEBOUNCE_SECONDS (e.g. 10) to avoid waiting two minutes.
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
OWNER_TG, CLIENT_TG = 5550001, 7770001
_ids = itertools.count(int(time.time()))

MESSAGES = {
    "en": [
        "Hi! How are you?",
        "Please add card payments to the website.",
        "Also the feedback form on the Contacts page does not send messages, please fix it.",
        "Can we move the launch date one week earlier?",
        "And we still need card payments, our customers keep asking.",
    ],
    "ru": [
        "Привет, как дела?",
        "Добавьте, пожалуйста, оплату картой на сайте.",
        "Форма обратной связи на странице контактов не отправляет сообщения, исправьте, пожалуйста.",
        "Сократим срок на неделю?",
        "И всё-таки нужна оплата картой, клиенты спрашивают.",
    ],
}


def wait(c: httpx.Client, url: str, done, timeout: float = 300) -> dict:  # type: ignore[no-untyped-def]
    start = time.time()
    while True:
        data = c.get(url).raise_for_status().json()
        if done(data):
            return data
        if time.time() - start > timeout:
            raise SystemExit(f"timeout waiting for {url}")
        time.sleep(1.5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000/api/v1")
    ap.add_argument("--lang", default="en", choices=["en", "ru"])
    ap.add_argument("--synthetic", action="store_true", help="acknowledge that Telegram is simulated")
    args = ap.parse_args()
    if not args.synthetic:
        sys.exit("Refusing to run without --synthetic: this script fabricates Telegram updates.")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not secret:
        sys.exit("TELEGRAM_WEBHOOK_SECRET must be set (the same value as the server).")
    print("!! SYNTHETIC Telegram data: connection, chat and client are fictional.\n")

    c = httpx.Client(base_url=args.api, timeout=120)
    hook = httpx.Client(base_url=args.api, timeout=30, headers={"X-Telegram-Bot-Api-Secret-Token": secret})

    def tg(update: dict) -> str:
        update = {"update_id": next(_ids), **update}
        return str(hook.post("/integrations/telegram/webhook", json=update).raise_for_status().json()["outcome"])

    email = f"telegram-demo-{uuid.uuid4().hex[:6]}@example.com"
    tok = c.post("/auth/register", json={"email": email, "password": "correct horse battery", "display_name": "Demo"})
    c.headers["Authorization"] = f"Bearer {tok.raise_for_status().json()['access_token']}"
    ws = c.post("/workspaces", json={"name": "Northwind Studio (demo)"}).raise_for_status().json()["id"]
    p = c.post("/projects", json={"workspace_id": ws, "title": "Corporate website", "client_name": "Aster Logistics",
                                  "currency": "KZT", "budget": "1000000"}).raise_for_status().json()
    pid = p["id"]
    print(f"user {email}  workspace {ws}  project {pid}")

    fixture = "scope_contract.pdf" if args.lang == "en" else "scope_contract_ru.docx"
    c.post(f"/projects/{pid}/documents", files={"file": (fixture, (FIX / fixture).read_bytes())}).raise_for_status()
    wait(c, f"/projects/{pid}/documents", lambda d: all(x["parse_status"] == "PARSED" for x in d))
    c.post(f"/projects/{pid}/scope/extract", json={}).raise_for_status()
    state = wait(c, f"/projects/{pid}/scope",
                 lambda s: s["extraction_job"] and s["extraction_job"]["status"] in ("SUCCEEDED", "FAILED"))
    draft = state["draft"]
    items = [{"id": i["id"], "title": i["title"], "description": i["description"], "inclusion_type": i["inclusion_type"],
              "acceptance_criteria": i["acceptance_criteria"], "source_span_ids": [e["span_id"] for e in i["evidence"]],
              "accepted": True} for i in draft["items"] if i["evidence"]]
    d = c.put(f"/projects/{pid}/scope/draft", json={"expected_revision": draft["draft_revision"], "items": items})
    c.post(f"/projects/{pid}/scope/approve",
           json={"expected_revision": d.raise_for_status().json()["draft_revision"], "note": "reviewed (demo)"}
           ).raise_for_status()
    print(f"baseline approved with {len(items)} items (extracted by the real AI provider)")

    link = c.post(f"/workspaces/{ws}/integrations/telegram/link-intents").raise_for_status().json()["deep_link"]
    nonce = link.split("start=", 1)[1]
    now = int(time.time())
    print("start      ->", tg({"message": {"message_id": 1, "date": now, "chat": {"id": OWNER_TG, "type": "private"},
                                      "from": {"id": OWNER_TG, "is_bot": False, "first_name": "Demo", "username": "demo_owner"},
                                      "text": f"/start {nonce}"}}))
    conn_id = f"sim-{uuid.uuid4().hex[:8]}"
    print("connection ->", tg({"business_connection": {"id": conn_id, "date": now, "is_enabled": True,
                                                       "user": {"id": OWNER_TG, "is_bot": False, "first_name": "Demo", "username": "demo_owner"},
                                                       "rights": {"can_read_messages": True}}}))

    mid = itertools.count(100)

    def client_says(text: str) -> str:
        return tg({"business_message": {"message_id": next(mid), "date": int(time.time()), "business_connection_id": conn_id,
                                        "chat": {"id": CLIENT_TG, "type": "private", "first_name": "Aster", "last_name": "Logistics"},
                                        "from": {"id": CLIENT_TG, "is_bot": False, "first_name": "Aster"}, "text": text}})

    print("first msg  ->", client_says(MESSAGES[args.lang][0]))
    c.post(f"/projects/{pid}/telegram/chat-binding", json={"chat_id": CLIENT_TG}).raise_for_status()
    c.patch(f"/projects/{pid}/telegram/monitoring", json={"enabled": True, "privacy_acknowledged": True}).raise_for_status()
    for text in MESSAGES[args.lang][1:4]:
        print("client     ->", client_says(text))
    b = wait(c, f"/projects/{pid}/telegram/chat-binding",
             lambda x: x["last_batch"] and x["last_batch"]["state"] != "OPEN", timeout=900)
    print("batch      ->", b["last_batch"]["state"], b["last_batch"]["outcome"])
    reqs = c.get(f"/projects/{pid}/requests").json()
    if reqs:
        wait(c, f"/requests/{reqs[0]['id']}", lambda r: r["status"] != "ANALYZING", timeout=600)
    time.sleep(3)
    print("repeat     ->", client_says(MESSAGES[args.lang][4]))
    wait(c, f"/projects/{pid}/telegram/chat-binding",
         lambda x: x["last_batch"] and x["last_batch"]["state"] != "OPEN", timeout=900)
    time.sleep(8)
    print("\nCases (each is a suggestion for human review):")
    for s in c.get(f"/projects/{pid}/commercial-signals?status=all").json():
        detail = c.get(f"/commercial-signals/{s['id']}").json()
        print(f"- [{s['category']}] x{s['occurrences']} {s['summary']}")
        for e in detail["evidence"]:
            print(f"    chat: {e['quote']!r} ({e['state']})")
        if detail["finding"]:
            for ev in detail["finding"]["evidence"]:
                print(f"    contract ({ev['polarity']}): {ev['quote'][:110]!r}")
    print(f"\nOpen the project: /projects/{pid}/telegram  (sign in as {email} / correct horse battery)")


if __name__ == "__main__":
    main()
