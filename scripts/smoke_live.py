"""Live smoke test of the full workflow against a RUNNING API + worker with the REAL AI provider.

    uv run --project apps/api python scripts/smoke_live.py [--api http://localhost:8000/api/v1] [--lang en|ru]

It registers a fresh user, uploads the synthetic contract, extracts and approves the scope,
analyses the synthetic client message, prices one change, approves it and downloads the PDF.
Prints every finding with its evidence so a human can judge the AI output.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"


def wait(client: httpx.Client, url: str, done, timeout: float = 300) -> dict:  # type: ignore[no-untyped-def]
    start = time.time()
    while True:
        data = client.get(url).raise_for_status().json()
        if done(data):
            return data
        if time.time() - start > timeout:
            raise SystemExit(f"timeout waiting for {url}: {data}")
        time.sleep(1.5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000/api/v1")
    ap.add_argument("--lang", default="en", choices=["en", "ru"])
    args = ap.parse_args()
    c = httpx.Client(base_url=args.api, timeout=60)

    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    tok = c.post("/auth/register", json={"email": email, "password": "smoke-test-password", "display_name": "Smoke"})
    c.headers["Authorization"] = f"Bearer {tok.raise_for_status().json()['access_token']}"
    ai = c.get("/system/ai").json()
    print("AI:", ai["provider"], ai["model"], "configured" if ai["configured"] else f"NOT CONFIGURED ({ai['error']})")
    ws = c.post("/workspaces", json={"name": "Smoke studio"}).raise_for_status().json()
    proj = c.post("/projects", json={"workspace_id": ws["id"], "title": "Smoke: corporate website",
                                     "client_name": "Aster Logistics", "currency": "KZT"}).raise_for_status().json()
    pid = proj["id"]
    fixture = "scope_contract.pdf" if args.lang == "en" else "scope_contract_ru.docx"
    doc = c.post(f"/projects/{pid}/documents", files={"file": (fixture, (FIX / fixture).read_bytes())}).raise_for_status().json()
    doc = wait(c, f"/documents/{doc['document']['id']}", lambda d: d["parse_status"] not in ("PENDING", "PARSING"))
    print("Parsed:", doc["parse_status"], doc["span_count"], "spans")

    t0 = time.time()
    ex = c.post(f"/projects/{pid}/scope/extract", json={}).raise_for_status().json()
    job = wait(c, f"/jobs/{ex['job']['id']}", lambda j: j["status"] in ("SUCCEEDED", "FAILED"))
    if job["status"] != "SUCCEEDED":
        raise SystemExit(f"extraction failed: {job['last_error_code']} {job['last_error']}")
    draft = c.get(f"/projects/{pid}/scope").json()["draft"]
    print(f"\nScope candidates ({time.time() - t0:.1f}s):")
    for i in draft["items"]:
        print(f"  [{i['inclusion_type']:9}] {i['title']}  <- {i['evidence'][0]['text'][:70]!r}")
    items = [{"id": i["id"], "title": i["title"], "description": i["description"], "inclusion_type": i["inclusion_type"],
              "acceptance_criteria": i["acceptance_criteria"], "source_span_ids": [e["span_id"] for e in i["evidence"]],
              "accepted": True} for i in draft["items"]]
    d = c.put(f"/projects/{pid}/scope/draft", json={"expected_revision": draft["draft_revision"], "items": items}).raise_for_status().json()
    b = c.post(f"/projects/{pid}/scope/approve", json={"expected_revision": d["draft_revision"]}).raise_for_status().json()
    print("Baseline approved: v", b["version"], b["baseline_hash"][:16])

    msg_file = "client_change_message.txt" if args.lang == "en" else "client_change_message_ru.txt"
    req = c.post(f"/projects/{pid}/requests", json={"message_text": (FIX / msg_file).read_text().strip()}).raise_for_status().json()
    t0 = time.time()
    run = c.post(f"/requests/{req['id']}/analyze", json={}).raise_for_status().json()
    run = wait(c, f"/analysis-runs/{run['analysis_run_id']}", lambda r: r["status"] in ("SUCCEEDED", "NEEDS_REVIEW", "FAILED"))
    print(f"\nAnalysis {run['status']} in {time.time() - t0:.1f}s, model={run['model']}, tokens={run['token_usage']}")
    if run["status"] == "FAILED":
        raise SystemExit(f"analysis failed: {run['error_code']} {run['error_message']}")
    req = c.get(f"/requests/{req['id']}").json()
    items_by_id = {i["id"]: i for i in req["items"]}
    change = None
    for f in run["findings"]:
        print(f"\n  «{items_by_id[f['request_item_id']]['exact_text']}»")
        print(f"   -> {f['category']} (ai={f['ai_category']}, review={f['review_status']}, conf={f['model_confidence']})")
        print(f"      {f['reason']}")
        for e in f["evidence"]:
            print(f"      [{e['polarity']}] {e['inclusion_type'] or 'text'}: “{e['quote'][:90]}” ({e['document_title']} p.{e['page']})")
        for q in f["clarifying_questions"]:
            print(f"      ? {q}")
        if f["policy_notes"] or f["validation_errors"]:
            print(f"      policy={f['policy_notes']} validation={f['validation_errors']}")
        if f["category"] == "CHANGE_CANDIDATE" and change is None:
            change = f

    if change is None:
        print("\nNo change candidate found; stopping before pricing.")
        sys.exit(0)
    c.post(f"/requests/{req['id']}/findings/{change['id']}/review", json={"decision": "ACCEPT"}).raise_for_status()
    c.put(f"/projects/{pid}/rates", json={"expected_revision": 0, "rates": [{"role": "Developer", "hourly_rate": "10000"}]}).raise_for_status()
    est = c.post(f"/requests/{req['id']}/estimates", json={"request_item_id": change["request_item_id"],
              "lines": [{"kind": "HOURLY", "role": "Developer", "hours": "24"}]}).raise_for_status().json()
    c.post(f"/estimates/{est['id']}/approve").raise_for_status()
    co = c.post("/change-orders", json={"request_id": req["id"], "estimate_ids": [est["id"]], "language": args.lang}).raise_for_status().json()
    c.post(f"/change-orders/{co['id']}/submit").raise_for_status()
    co = c.post(f"/change-orders/{co['id']}/approve", json={"revision_id": co["current"]["id"],
                "content_hash": co["current"]["content_hash"]}).raise_for_status().json()
    x = c.post(f"/change-orders/{co['id']}/export", json={}).raise_for_status().json()
    pdf = c.get(x["download_path"]).raise_for_status()
    out = ROOT / "var" / f"smoke-change-order-{args.lang}.pdf"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(pdf.content)
    print(f"\nChange order #{co['number']} {co['status']} total={co['current']['content']['total']} KZT -> PDF {out} "
          f"({len(pdf.content)} bytes, hash {x['content_hash'][:16]})")


if __name__ == "__main__":
    main()
