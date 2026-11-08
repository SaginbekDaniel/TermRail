# TermRail

**Contract-first commercial control for client projects.** TermRail turns a signed contract into an
approved scope baseline, checks client requests against it with evidence, and prepares human-reviewed
change orders. An optional read-only Telegram Business connector watches one chosen client chat and surfaces
potential changes for review. TermRail never sends messages, prices work or accepts anything on its own.

Canonical specification: [`TERMRAIL_MASTER_SPEC.md`](TERMRAIL_MASTER_SPEC.md) ·
What actually works and how it was verified: [`IMPLEMENTATION_REPORT.md`](IMPLEMENTATION_REPORT.md)

## Layout

| Path | What |
|---|---|
| `apps/api` | FastAPI, SQLAlchemy (async), PostgreSQL, Alembic, durable Postgres job worker |
| `apps/web` | React + TypeScript + Vite, React Query, RU/EN i18n |
| `fixtures` | Clearly synthetic contracts and client messages (`scripts/make_fixtures.py`) |
| `scripts` | `verify_brand.py`, `smoke_live.py`, `telegram_simulate.py`, `telegram_setup_webhook.py` |
| `docs` | Architecture, threat model, superseded v1 spec |

## Local development

Requires Python 3.13 + [uv](https://docs.astral.sh/uv/), Node 22, PostgreSQL 16.

```bash
cp .env.example apps/api/.env   # then fill in values; never commit them
```

```bash
cd apps/api && uv sync --group dev && uv run alembic upgrade head
```

```bash
cd apps/api && uv run uvicorn app.main:app --port 8000      # API (set RUN_WORKER_IN_PROCESS=true, or:)
```

```bash
cd apps/api && uv run python -m app.worker                  # worker
```

```bash
cd apps/web && npm ci && npm run dev                         # http://localhost:5173
```

## Checks

```bash
cd apps/api && uv run ruff check . && uv run mypy app && uv run pytest -q   # needs PostgreSQL (TEST_DATABASE_URL)
```

```bash
cd apps/web && npm run lint && npm run typecheck && npm test && npm run build
```

```bash
python3 scripts/verify_brand.py
```

Backend tests use a real PostgreSQL database (`termrail_test` by default) and real migrations. The only
substitute is the AI provider: `APP_ENV=test` enables a deterministic fake that can never run elsewhere.

## Telegram Business setup (per environment)

1. In @BotFather create a bot for this environment and enable **Business Mode**.
2. Set `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, a strong
   `TELEGRAM_WEBHOOK_SECRET` and a `TELEGRAM_DATA_KEY` (see `.env.example`). Use different values for
   staging and production.
3. Deploy the API behind HTTPS, then register the webhook:
   ```bash
   uv run --project apps/api python scripts/telegram_setup_webhook.py set --url https://<api-host>/api/v1/integrations/telegram/webhook
   ```
4. Schedule the daily retention job: `python -m app.integrations.telegram.retention`.
5. In the app: Project → Telegram → *Connect Telegram*, open the link and press Start, then in Telegram
   *Settings → Telegram Business → Chatbots* add the bot with **Only selected chats**. Pick the client chat
   once it has a new message, confirm the privacy notice and start monitoring.

For a rehearsal without a real account, `scripts/telegram_simulate.py --synthetic` plays Telegram's side
against a running API (all Telegram data is fictional and labelled as such).
