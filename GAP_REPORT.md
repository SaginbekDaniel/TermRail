# TermRail — Phase 0 Gap Report

**Date:** 2026-11-08 · **Author:** coding agent (Claude Code, cloud session) · **Spec:** `TERMRAIL_MASTER_SPEC.md` (v2, Telegram)

This report records the repository's *observed* state before any change, compares it with the v2
specification, and fixes the plan. Every statement below is backed by a command that was actually run in
this session; nothing is inferred from earlier agents' claims.

## 1. Git state (captured before editing)

| Item | Observed |
|---|---|
| Working branch | `claude/awesome-bell-fu7fyz` (designated for this session) at `f432b74` |
| Default branch | `claude/busy-wozniak-2thmet` at `f432b74` (identical) |
| `termrail/base` | `cef0fd4` = `f432b74` + one commit adding `TERMRAIL_MASTER_SPEC.md` (v1, 1437 lines) |
| Uncommitted changes | none (`git status` clean, `git diff --stat` empty) |
| History | 2 product commits: API (`f8598f4`), web (`f432b74`) |

**Reconciliation:** `termrail/base` is a strict fast-forward of the working branch, so it was merged with
`git merge --ff-only` (no conflicts, no rewrite). No other local machine's uncommitted work is visible from
the cloud; nothing was reset, cleaned or force-pushed.

## 2. Baseline checks (before any change)

| Check | Command | Result |
|---|---|---|
| Backend tests | `uv run pytest -q` (real PostgreSQL 16, real Alembic migrations) | **63 passed** |
| Backend lint | `uv run ruff check .` | **16 errors** (pre-existing) |
| Backend types | `uv run mypy app` | **17 errors in 8 files** (pre-existing) |
| Web lint | `npm run lint` (oxlint) | pass |
| Web types | `npm run typecheck` | pass |
| Web unit tests | `npm test` (vitest) | **exit 1 — no test files exist** |
| Web build | `npm run build` | pass (chunk-size warning) |
| CI | `.github/workflows` | **absent** |

## 3. What exists (verified in code)

The v2 spec's audit table (§2) is accurate. Confirmed modules: FastAPI app with tenant-scoped deps
(`require_workspace`/`require_project`, foreign objects → 404), local + Supabase JWT auth, Postgres durable
jobs (`FOR UPDATE SKIP LOCKED`, lease recovery, retry/backoff, FAILED as dead letter), PDF/DOCX parsing with
SHA-256 and source spans, AI scope extraction with manual review, immutable approved baselines (DB
triggers), request intake with idempotency, evidence-gated analysis (server-built candidate refs,
fabricated refs rejected, quotes always server-sourced, "silence ≠ change" policy), Decimal estimates
from rate cards, change-order revisions + internal approval + PDF export, append-only audit, typed RU/EN
i18n with compile-time key parity.

## 4. Gaps against v2

| Area | Gap | Plan |
|---|---|---|
| Brand | 76 active references to the legacy brand in 25 tracked files (UI strings, `<title>`, OpenAPI title, PDF footer/author, package names, logger names, JWT issuer, localStorage keys, env defaults, fixtures, **DB function names in migration 0002**) | Phase 1 rebrand; DB functions renamed by a new additive migration (triggers bind by OID → safe `ALTER FUNCTION … RENAME`); migration 0002 left untouched as history; `scripts/verify_brand.py` enforces it |
| Spec | Two master documents would conflict | v2 becomes `TERMRAIL_MASTER_SPEC.md`; v1 moved to `docs/specs/` as superseded history, its CAP/Start-Work/Receipt requirements carried into a backlog section |
| Telegram | No connector, webhook, link flow, chat binding, batching, signals | Phases 2–3 |
| Request channel | `requests.channel` check allows only `MANUAL`,`EMAIL`; no origin/provenance | Additive migration: `TELEGRAM`, `origin`, `source_batch_id` |
| Jobs | No delayed scheduling or deferral; time = SQL `now()` (not testable without sleeping) | Add `run_at` + deferral + injectable clock |
| Commercial Authorization (v1 CAP) | Tasks, `Start Work` gate, Authorization Receipt, client acceptance, baseline v2 from accepted CO: **not implemented** | Out of scope for this slice; kept as explicit P1 backlog, no UI claims |
| Web tests | None | Add vitest coverage for the new Telegram UI |
| CI | None | Not added in this slice (no secrets/infra decision made by owner) — listed as next step |
| Pre-existing lint/type errors | 16 ruff, 17 mypy | Fix in Phase 1 (root causes, not ignores) |

## 5. Spec conflicts and decisions

1. **Outbound messages as AI context (v2 §3.7):** the existing analysis prompt has no "context" slot. Feeding
   contractor messages into the "client message" would let the splitter extract the contractor's words as
   requirements. **Decision:** only inbound client messages go to the model in this slice; outbound
   messages are stored for evidence/timeline only. Logged as a known gap.
2. **Chat discovery metadata (v2 §9 `telegram_chat_candidates`):** Telegram only sends updates for chats the
   owner allowed in Business settings. Minimal metadata (chat id, display name, last seen) is kept for those
   chats so the picker can work; **no message body** of an unselected chat is ever persisted or sent to AI.
   Connecting the bot is the informed opt-in, disclosed in the UI.
3. **Link order:** a `business_connection` update may arrive *before* the `/start` ownership handshake.
   Such a connection is stored as `UNCLAIMED` with no workspace and ingests nothing until a verified
   handshake from the *same* Telegram user id claims it.
4. **No reply to `/start`:** replying would be an external send; `ALLOW_EXTERNAL_SEND=false` forbids it.
   The web UI polls and confirms the handshake instead.
5. **Analysis failure for a Telegram batch:** v2 §8.3 forbids silent "no change". A terminal failure creates
   a `UNANALYZED` signal asking for manual review.
6. **v1 spec §4.1 demands Start Work gate in P0** while v2 §12 moves it to P1. v2 is the canonical target;
   the v1 requirement is preserved in the backlog, not deleted.

## 6. Environment facts

PostgreSQL 16 started locally (`termrail`/`termrail_test` databases). No Telegram bot token or Business
account is available in this session → **live Telegram verification will be BLOCKED**; all Telegram tests
use typed synthetic updates through the real webhook route and real database.
