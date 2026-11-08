# TERMRAIL — MASTER PRODUCT & ENGINEERING SPECIFICATION V2
## Contract-first Telegram Intelligence & Commercial Authorization

**Версия:** 2.0 — 2026-11-08  
**Статус:** нормативная спецификация для реализации; НЕ утверждение, что функции уже работают  
**Продукт:** TermRail — AI-native B2B SaaS для контроля коммерческих договорённостей и изменений проекта  
**Репозиторий:** https://github.com/SaginbekDaniel/TermRail  
**Целевая среда разработки:** Claude Desktop / Claude Code Cloud  
**Язык UI:** RU/EN; KK — отдельный этап после проверки полноты переводов  
**Приоритет:** сохранить и усилить существующий коммерческий контур; добавить Telegram без небезопасной перестройки ядра

> **Основная идея:** пользователь создаёт проект, загружает договор и ТЗ, проверяет и утверждает извлечённый AI объём работ, подключает Telegram Business и явно выбирает чат заказчика. Только после этого TermRail анализирует новые сообщения в данном чате, обнаруживает потенциальные отклонения от договорённостей, показывает доказательства и готовит черновик коммерческого изменения, который проверяет человек. Никаких автоматических счетов, обещаний, «подписей» или сообщений от имени пользователя без отдельного явного разрешения.

---

# 0. НЕПРЕЛОЖНЫЕ ПРАВИЛА ДЛЯ CODING AGENT

1. **Прочитай репозиторий до изменения кода:** Git status/branch/HEAD, всю актуальную спецификацию, `apps/api`, `apps/web`, Alembic, тесты, `scripts`, `.env.example`, конфигурацию окружений. Сравни фактическое состояние с документом и запиши gap analysis.
2. **Не доверяй словам предыдущих агентов:** ранее заявленные тесты/функции не равны выполненным. Любое заявление «готово» подтверждается реальным кодом и результатом команд.
3. **Ничего не потеряй:** не выполнять `git reset --hard`, `git clean -fd`, destructive schema reset, force-push, удаление БД/данных/секретов/чужих веток. Не переписывать историю Git.
4. **История работы:** перед интеграцией проверить состояние двух известных веток (`claude/busy-wozniak-2thmet` и `termrail/base`) и наличие `TERMRAIL_MASTER_SPEC.md`; сохранить новые локальные/облачные изменения до разрешения конфликтов. Из старой спецификации перенести незавершённые обязательные инварианты, а не забыть их.
5. **Удалить бренд `ScopeLock` из активного продукта полностью**, но НЕ удалять рабочие модули, таблицы, миграции, тесты и данные только по наличию слова. Правила ребрендинга — раздел 4. Исторические Git-коммиты не переписывать.
6. **Один источник истины:** этот документ v2 — целевой продуктовый документ. Если в репозитории находится старый `TERMRAIL_MASTER_SPEC.md`, согласовать и обновить его, не оставляя два конфликтующих «master» файла. Сохранить нужные исторические ADR/требования.
7. **Никаких фиктивных реализаций:** мок-Telegram используется только в явно обозначенных тестах/DEMO. Не рисовать «подключён» при отсутствии реального BusinessConnection. AI fake-provider — исключительно test-режим.
8. **Безопасность по умолчанию:** никакого пользовательского MTProto/userbot, Telethon/Pyrogram-авторизации по личному номеру, OTP, Telegram session string, обхода API или скрейпинга клиентских чатов. Только официальный Telegram Business Bot API.
9. **Никогда не отправлять ничего в Telegram автоматически в MVP.** `ALLOW_EXTERNAL_SEND=false` сохраняется. Система готовит и экспортирует черновики, человек отправляет вручную. Реальную отправку проектировать как отдельный P1 feature flag с явным подтверждением для каждого сообщения.
10. **Атомарность, изоляция и idempotency:** любая обработка webhook, jobs, alert и change order обязана выдерживать повторы, параллельность и остановку воркера.
11. **Область изменений:** держать изменения в отдельной ветке; не коммитить секреты; не пушить и не мерджить без разрешения; для Cloud можно подготовить draft PR после проверки (если есть авторизация на запись).
12. **Финиш:** только после реальных unit, integration, security, frontend, E2E проверок; если инфраструктура недоступна — отчёт о блокерах, без фальшивого PASS.

# 1. ПРОДУКТОВОЕ ПОЗИЦИОНИРОВАНИЕ

**Один тезис:** «Jira показывает, что делает команда. TermRail проверяет, согласовано ли это с заказчиком и на каких условиях». Telegram — канал обнаружения потенциальных изменений, а НЕ единственный продукт.

**Проблема:** IT-компании, веб-студии и агентства часто согласовывают дополнительные функции и сроки в чатах. Эти сообщения не попадают в утверждённое ТЗ и в финансовые договорённости, поэтому исполнитель начинает работу, не согласовав изменение цены, объёма или дедлайна.

**Целевая аудитория MVP:** небольшие digital-/IT-агентства с 2–20 специалистами, фиксированными проектными бюджетами и клиентскими чатами Telegram; вторично — фрилансеры.

**Ценность:** обнаружить риск на основании конкретных фактов; отличить bug fix от платного расширения; упростить и документировать согласование. Не обещать «100% точность», «гарантированное взыскание» и «юридическую подпись».

## 1.1 Принципы

- **Contract first:** нет утверждённой baseline — нет активного коммерческого анализа чата.
- **Explicit chat:** пользователь сам выбирает и подтверждает чат, не весь Telegram.
- **Evidence first:** каждое уведомление содержит точные сообщения + ссылки на положения договора (либо явно помечено, что доказательств недостаточно).
- **Conservative AI:** сомнения → `NEEDS_REVIEW`; отсутствие пункта в договоре не означает автоматически «платная работа».
- **Human approval:** AI не изменяет утверждённую baseline, не назначает цену, не принимает решение за клиента, не отправляет сообщение.
- **Versioned truth:** запрос оценивается относительно конкретной утверждённой версии договора/ТЗ и ранее одобренных изменений.
- **Client fairness:** гарантийные дефекты, согласованная работа, уточнения и ошибки подрядчика не должны автоматически монетизироваться.
- **Privacy by design:** по умолчанию нулевая обработка содержимого невыбранных чатов.

# 2. ДОСТОВЕРНОЕ ИСХОДНОЕ СОСТОЯНИЕ РЕПОЗИТОРИЯ

**Статический аудит GitHub от 2026-11-08 (обязательно перепроверить HEAD при запуске Claude):**

| Слой | Обнаружено |
|---|---|
| Backend | `apps/api`: FastAPI, Python >=3.13, SQLAlchemy async, PostgreSQL, Alembic |
| Frontend | `apps/web`: React, TypeScript, Vite, React Query, React Router |
| AI | `apps/api/app/llm`: Gemini/OpenAI-compatible адаптер, test-only fake |
| Jobs | Postgres backed durable jobs, leases, retry/dead-letter |
| Документы | PDF/DOCX upload, SHA-256, парсинг с anchor/source spans |
| Договор | extracted scope candidates, manual review, approved immutable baselines |
| Запросы | `ClientRequest`, `RequestItem`, анализ с доказательствами, ручной review |
| Коммерция | Decimal-оценка, ChangeOrder revision/approval, PDF export, audit |
| RBAC | workspaces, members, roles, проверка tenant-доступа |
| Telegram | Не обнаружен реальный connector, webhook и выбор чата |
| Связь с задачами | Старый master spec требует gate перед `Start Work`, но в опубликованном коде полный контур не подтверждён |
| CI | Наличие рабочих GitHub Actions не подтверждено |
| Брендинг | Обнаружены остатки `ScopeLock` в активном коде и названиях пакетов |

**Ветки на момент аудита:** default `claude/busy-wozniak-2thmet`, `termrail/base` содержала дополнительный `TERMRAIL_MASTER_SPEC.md`. Старый master определял Commercial Authorization Layer, `Start Work` gate, Receipt, клиентское подтверждение. Эти требования нельзя случайно потерять из-за новой идеи с Telegram.

Ключевые области для переиспользования:

- `apps/api/app/api/v1/documents.py` — документы;
- `apps/api/app/api/v1/scope.py` и `domains/scope.py` — baseline;
- `apps/api/app/api/v1/requests.py` и `domains/intake.py` — запрос;
- `apps/api/app/domains/analysis.py` — разбивка, evidence-based AI-анализ, review;
- `apps/api/app/domains/evidence.py` — server validation и policy gates;
- `apps/api/app/domains/change_orders.py`, `estimates.py` — коммерческий workflow;
- `apps/api/app/jobs/queue.py`, `jobs/runner.py` — durable jobs;
- `apps/api/app/core/config.py`, `api/deps.py` — настройки, роли, tenant isolation;
- `apps/web/src/features/projects/*`, `requests/*`, `change-orders/*`, `settings/*` — существующий UX.

**Не изменять эти модули вслепую:** сначала определить точку расширения с минимальным diff.

# 3. ОСНОВНОЙ END-TO-END СЦЕНАРИЙ

1. Менеджер создаёт workspace/project, указывает клиента, валюту и параметры проекта.
2. Загружает PDF/DOCX договор и, при необходимости, отдельное ТЗ/приложения.
3. Система парсит исходные документы с SHA-256, сохраняет source spans и извлекает в черновик: in-scope, exclusions, revision limits, warranty, change policy, сроки, pricing references.
4. Менеджер проверяет извлечённые пункты, исправляет ошибки и **утверждает baseline v1**. Без этого мониторинг на уровне commercial analysis не включается.
5. Открывает `Project → Integrations → Telegram` и подключает Telegram Business через защищённую процедуру привязки владельца (раздел 6).
6. В самом Telegram выдаёт Business Bot доступ только к нужным чатам. В TermRail выбирает один **реально обнаруженный и разрешённый** чат, подтверждает привязку к проекту и активирует monitoring.
7. Новые сообщения **только этого чата** поступают в webhook. За 2 минуты тишины после последнего релевантного сообщения собирается единый batch. Исходящие сообщения учитываются только как контекст, если доступ разрешён; AI не принимает их за новое клиентское требование.
8. Дешёвый детерминированный фильтр отбрасывает бессодержательные сообщения, реакции, сервисные события, не относящиеся к коммерческому изменению. При неоднозначности не отбрасывает потенциально значимую просьбу.
9. AI сверяет batch с текущей утверждённой baseline, предыдущими решениями, warranty и уже существующими candidate signals. Формирует возможный `CHANGE_CANDIDATE`, `IN_SCOPE`, `BUG_FIX`, `AMBIGUOUS`, `INSUFFICIENT_EVIDENCE` с отсылками к источникам.
10. Дедупликация объединяет повторные формулировки одного и того же запроса. Даже если 5 сообщений про бонусную программу пришли отдельно, появляется не более одного активного коммерческого кейса.
11. Если найден новый существенный риск, менеджер видит внутреннее уведомление и конкретную карточку: «Что попросил клиент», «Где в договоре», «Почему нужен review», «Предыдущие решения», «Следующий безопасный шаг».
12. Менеджер выбирает `Dismiss`, `Mark in scope / bug fix`, `Ask clarification`, `Estimate`, `Create change-order draft`. Действия записываются в audit.
13. При составлении estimate цены берутся **только** из утверждённого rate card и вручную подтверждённых часов/фиксированной суммы, никаких оценок как факта от LLM.
14. Создаётся draft Change Order. Пока нет явного утверждения менеджера и подтверждения клиента отдельным действительным workflow, нет нового коммерческого основания. PDF может быть экспортирован с честным DRAFT/APPROVED_INTERNAL статусом.
15. В следующих фазах согласованный Change Order обновляет baseline v2 и позволяет Commercial Authorization Check перед работой. Этот шаг нельзя имитировать без реализованной state machine.

## 3.1 Сценарии обязательной классификации

- «Привет, как дела?» → тихо игнорировать; AI не вызывать.
- «Когда будет готов сайт?» при прежнем дедлайне → без коммерческого сигнала.
- «Добавь бонусную систему» при отсутствии в согласованном scope → кандидат + human review.
- «Исправьте вашу неработающую кнопку» при действующей гарантии → `BUG_FIX`, не платное расширение по умолчанию.
- «А давай то же самое, но другой цвет» → контекстный анализ revision limit; при неопределённости review.
- «Сократим срок на неделю?» → `TIMELINE_CHANGE_CANDIDATE` как внутренний сигнал, а не новая цена по умолчанию.
- «Согласен на 80 000 ₸» → зафиксировать контекст, **НЕ** считать платёж полученным или юридическое подтверждение достаточным.
- Повторы одного запроса → один case с растущей доказательной историей.
- Удаление/редактирование сообщения до анализа → использовать актуальную версию или tombstone; после решения → пометить evidence как changed/revoked и отправить на review.

# 4. ПОЛНЫЙ РЕБРЕНДИНГ: SCOPELOCK → TERMRAIL

**Требование пользователя:** в текущей активной кодовой базе, интерфейсе и выпускаемых артефактах не должно остаться бренда `ScopeLock` в каком-либо регистре. Нельзя оставлять старое имя как продуктовый синоним.

**Что проверить и исправить:**

- Визуальный UI: логотип, `<title>`, meta, favicon, описания, header/sidebar, emails, onboarding, demo, tooltips, alerts, translations, screenshots и README.
- API: FastAPI `title`, OpenAPI meta, generated docs, public examples, error responses, telemetry service/display names.
- Пакеты: `apps/api/pyproject.toml` (`name`, `description`), `apps/web/package.json`, lock-файлы, script names, import paths, log names.
- Конфигурация: `.env.example`, dev-only database example, Docker/compose/CI scripts и deploy names **только если они в проекте**, тестовые fixtures.
- Документы: commercial PDF headers/footers, шаблоны, API examples, user docs, demo scripts.
- Репозиторий: README, contributor docs, master spec, comments и тесты, где старый бренд не нужен для совместимости.
- Отдельно проверить Unicode/spelling/case: `ScopeLock`, `scopelock`, `scope-lock`, `SCOPELOCK`, `Scope Lock`.

**Граница безопасности:**

1. НЕ удалять домены `scope`, `scope_items`, `scope_baselines`: это термин предметной области, а не старый бренд.
2. НЕ удалять существующие миграции и не переименовывать production-таблицы ради косметики. Исторические migration IDs, выпущенные импорты, старые пользовательские данные и audit immutable остаются доступными.
3. Если используется существующая production/staging БД с названием `scopelock`, менять подключение только через безопасную конфигурацию/документированное provisioning. Не выполнять автоматический `DROP DATABASE`/RENAME или копирование секретов.
4. Обновлять lockfiles правильными package-manager командами, не вручную.
5. Наличие слова в историческом Git-коммите НЕ исправлять переписыванием истории. В новых активных tracked files выполнить `git grep -niE 'scopelock|scope-lock|scope lock'`; каждое оставшееся совпадение либо устранить, либо объяснить как строго необходимую техническую совместимость с тестом.
6. Тесты должны проверять публичный брендинг `TermRail`; никакого «прошло» без фактического запуска.

**Definition of done rebrand:** бренд `TermRail` во всех customer-visible UI/API/PDF/README; сборка и тесты работают; данные и контракты не повреждены; для прежних имён в legacy DB предусмотрена backward compatibility.

# 5. АРХИТЕКТУРА: МОДУЛЬНЫЙ МОНОЛИТ, НЕ МИКРОСЕРВИСЫ

Сохранить текущий FastAPI + PostgreSQL + durable worker + React стек. Не вводить отдельные Kafka, Redis, Celery, vector DB или Telegram user session storage для MVP. Существующий Postgres job runner достаточно расширить при условии проверки конкурентных блокировок и durable scheduling.

```text
┌─────────────────────── TermRail Web ─────────────────────────────┐
│ Projects │ Documents │ Scope Baseline │ Telegram │ Inbox │ CO  │
└──────────────────────────┬───────────────────────────────────────┘
                           │ Authenticated API (RBAC + tenant scope)
                           ▼
┌─────────────────────── FastAPI ──────────────────────────────────┐
│ Identity/Projects/Documents/Scope/Requests/Analysis/ChangeOrder │
│ Telegram Link API + Chat Bindings + Findings/Review endpoints    │
│ Telegram Webhook (separate ingress, secret verification)        │
└──────────────┬───────────────────────────┬───────────────────────┘
               │                           │
               ▼                           ▼
     PostgreSQL: domain + jobs      Encrypted private storage
               │
               ▼
     Durable worker (claim/lease/retry)
       ├─ Telegram event normalization
       ├─ 2-minute batch finalization
       ├─ deterministic pre-filter
       ├─ existing analysis/evidence/policy
       └─ create internal finding/notification/CO draft
               │
               ▼
          Human review / explicit approval
```

## 5.1 Suggested directory placement

```text
apps/api/app/
  integrations/telegram/
    client.py               # HTTP client; no sends enabled in P0
    schemas.py              # Typed Bot API envelope subset
    ingress.py              # Verify/parse/update dispatch
    linking.py              # One-time connection binding
    chat_binding.py         # Authenticated workspace/project-scoped selection
    batching.py             # Persistent 120-second debounce
    signals.py              # Prefilter, semantic case clustering
    redaction.py            # PII safe logging/data minimization
  api/v1/telegram.py        # Authenticated REST endpoints
  api/telegram_webhook.py   # Separate public incoming webhook route
  db/models/telegram.py
  domains/telegram_ingest.py
  jobs/runner.py            # Register new job kinds
  tests/test_telegram_*.py
apps/web/src/features/telegram/
  TelegramConnectPanel.tsx
  TelegramChatPicker.tsx
  TelegramMonitoringSettings.tsx
  TelegramSignalsPanel.tsx
```

Paths may change to align with existing conventions, but **responsibilities and safeguards cannot disappear**. Reuse existing domain modules via service interfaces; no copy-paste LLM pipeline.

# 6. TELEGRAM BUSINESS: РЕАЛЬНЫЕ ПРАВА, ОНБОРДИНГ, ОГРАНИЧЕНИЯ

**Официальные источники:**

- https://core.telegram.org/bots/api
- https://core.telegram.org/bots/features#business-bots
- https://core.telegram.org/api/bots/connected-business-bots
- https://core.telegram.org/bots/api-changelog

## 6.1 Возможности и ограничения

- Bot должен поддерживать Business/Secretary Mode, настроенный через Telegram BotFather.
- Bot API выдаёт `business_connection`, `business_message`, `edited_business_message`, `deleted_business_messages`. Не смешивать с обычным `message`.
- BusinessConnection содержит `id`, `user`, `rights`, `is_enabled`. Актуальная схема прав использует `rights`, а не устаревшее standalone `can_reply`.
- Получаем только события, которые разрешены Telegram. **Нет универсального Bot API метода «список всех личных чатов пользователя» и общего чтения истории любой беседы.**
- Telegram пользователь сам задаёт доступные чаты; TermRail дополнительно требует подтверждения чат-привязки внутри приложения (двойная allowlist).
- Чат появляется в picker после реально доступного update с валидным `business_connection_id`. Не рисовать чужие контакты и вымышленные чаты из адресной книги.
- Telegram поддерживает один подключённый business bot на один аккаунт в рамках актуальной политики; UX должен предупредить об этом и не обещать коэкзистенцию со вторым ботом.
- Подключение Telegram Business bot согласно Telegram не требует Premium; однако UI и требования доступа могут меняться — проверить при реализации.
- `rights.can_reply` в Telegram ограничено условиями, например последним входящим сообщением. **P0 send запрещён независимо от rights.** Не запрашивать избыточные rights управления профилем/удаления сообщений.
- Нет автозагрузки старой истории. Для исторических данных рассмотреть позже opt-in импорт через предоставленный пользователем экспорт (с согласиями и ограничениями), НЕ через скрытый userbot.

## 6.2 Привязка аккаунта с доказательством владения

1. Авторизованный OWNER/MANAGER в TermRail создаёт одноразовый link intent: cryptographically random nonce, 10-min TTL, single use, bound к user + workspace и операции.
2. UI показывает проверенного Telegram Business бота и кнопку «Открыть в Telegram», deep link `/start <opaque_nonce>`; это связывает Telegram `from.id` со вошедшим пользователем, но **не предоставляет автоматически доступ к личным чатам**.
3. Пользователь подключает бота как Business Bot в настройках Telegram, разрешая ровно нужные клиентские чаты. Объяснить, какие данные бот видит.
4. На webhook `business_connection` сопоставить `BusinessConnection.user.id` с Telegram user_id, подтверждённым link intent; не доверять username/display name, не принимать присвоение чужого connection ID вручную.
5. Сохранять привязку лишь после подтверждения владельца и состояния `is_enabled`.
6. Если connection принадлежит другой workspace — отклонить или выполнить явную процедуру передачи/отвязки; не допускать скрытой shared connection между арендаторами.
7. При `is_enabled=false`, смене прав, переподключении и отзыве — немедленно приостановить ingestion, batch jobs, новые AI-вызовы и отправку, очистить ephemeral processing buffers по policy.
8. Для чата нужны фактически наблюдённые business updates именно этой connection, разрешённый тип (для MVP — private client chat) и явная привязка к одному активному проекту. Если чата нет в списке, UX «Разрешите чат в Telegram и дождитесь нового сообщения».
9. Не разрешать привязать один чат к двум активным проектам в рамках одного connection без отдельного явного UX и контекстного disambiguation; в MVP — запрет конфликта.

## 6.3 Webhook

- Продакшен: HTTPS `POST /api/v1/integrations/telegram/webhook` или аналог, защищённый `X-Telegram-Bot-Api-Secret-Token` из `setWebhook`; **constant-time** compare; секрет только из secret manager.
- Ограничения request body, JSON validation, safe failure, no query-string token, no bot token in logs.
- Принимать `allowed_updates`: `business_connection`, `business_message`, `edited_business_message`, `deleted_business_messages` и `message` для owner-link handshake (только если действительно требуется).
- Telegram может повторно присылать update при не-2xx ответе. Сначала **durably** фиксировать receipt/событие или релевантный результат в транзакции, только затем HTTP 2xx. На transient DB error отвечать non-2xx, чтобы Telegram повторил доставку.
- `getUpdates` и webhook одновременно не работают. Для local dev один режим ingestion; staging и production — webhook.
- Проверять событие по `business_connection_id`; никогда не принимать `workspace_id` из webhook payload.
- Не скачивать attachments, voice/video и не запускать OCR/ASR в P0. Обозначить unsupported media, не утверждать анализ контента, который не прочитан.
- Telegram webhook secret подтверждает конфигурацию webhook, но дополнительно нужны TLS, rate limit, replay protection, idempotent processing и мониторинг.

# 7. НАСТРОЙКИ SMART MONITORING — ОБЯЗАТЕЛЬНЫЕ ЗНАЧЕНИЯ ПО УМОЛЧАНИЮ

```yaml
telegram_monitoring:
  enabled: false                 # до утверждения baseline и выбора чата
  mode: smart
  selected_chats_only: true
  duplicate_suppression: true
  drafts_only: true
  message_debounce_seconds: 120
  max_batch_window_seconds: 900
  max_batch_messages: 100
  notifications: significant_findings_only
  process_history_on_connect: false
  process_attachments: false
  auto_send_messages: false
  require_approved_baseline: true
  require_human_review_for_change: true
```

**Параметр 120 секунд означает sliding debounce** после последнего сообщения в batch. При продолжающемся потоке принудительно закрыть batch после `max_batch_window_seconds` или количества сообщений, иначе вечный чат навсегда не обработается. Значения cap — стартовые значения для проектирования, затем нагрузочные тесты.

**Редактирование и удаление:** edits обновляют текущий snapshot и `content_version`; удаления — tombstone; при обработке snapshot фиксируется immutable provenance + version. Если доказательство позднее исчезает, нахождение помечается `EVIDENCE_CHANGED`, требуется переоценка и review.

**Обязательные условия активации:** project active; baseline approved; linked connection enabled; actor authorized; verified chat permission; user explicitly enabled monitoring; privacy notice/consent completed. Если хоть одно условие исчезло — fail closed.

# 8. SMART TRIGGER ENGINE: ПРАВИЛА, AI, ДЕДУПЛИКАЦИЯ

## 8.1 Пайплайн

1. Ingress → provenance validated → selected-chat binding.
2. Normalize only supported message text/caption, Telegram IDs, timestamps, direction, reply/thread metadata. No raw personal data in logs.
3. Event-level idempotency: `(bot_id, update_id)` unique, plus `(connection_id, chat_id, message_id, version)` for message upserts/edits.
4. Persist encrypted selected-chat message data according to retention; nonselected message body **не сохранять и не передавать в LLM**. Для discovery допустима минимальная metadata только с информированным opt-in.
5. Upsert per-chat OPEN batch, move `quiet_until = last_relevant_message_at + 120s`; schedule one durable finalize job. Lock row to avoid two concurrent finalizers.
6. Prefilter service messages/empty/irrelevant with deterministic rules; uncertainty escalates rather than losing a request.
7. Create Request through existing `intake` domain, not HTTP loopback. Extend `channel` to `TELEGRAM` with migration. Generated request must include `external provenance` and delegated `created_by`/actor type audit; do not forge human actions.
8. Run existing `analysis` against **current approved baseline** and capture baseline id/hash. Re-check staleness before committing finding. If baseline changes mid-analysis, mark stale and schedule manual re-evaluation; never silently apply to new baseline.
9. Existing `evidence.gate` must validate contract citations. Telegram source citations must reference exact stored message version and available Telegram message IDs. Unknown evidence -> NEEDS_REVIEW.
10. Semantic dedupe: compare active signals scoped to `(workspace, project, baseline/approved history)`; deterministic exact hashes + candidate similarity + business rule. LLM similarity can suggest merges but must never silently merge distinct requirements with different commercial consequences; allow human split/merge.
11. Surface at most one active notification per semantic case. Attach later matching messages to same case, update evidence and `last_seen_at`, keep history.
12. User action: dismiss/reclassify/clarify/estimate → Change Order draft. No auto billing or external send.

## 8.2 Business classifications

Reuse existing `IN_SCOPE`, `BUG_FIX`, `CHANGE_CANDIDATE`, `AMBIGUOUS`, `INSUFFICIENT_EVIDENCE`. Add **non-monetary signal types** at integration layer, e.g. `TIMELINE_CHANGE_CANDIDATE`, `PAYMENT_COMMITMENT_MENTION`, but do not classify them as chargeable without explicit contractual basis. Keep one canonical enum mapping and UI labels.

## 8.3 Evidence and prompt-injection protection

- Telegram content is **untrusted user data**, never system instructions. Ignore «забудь договор», «выставь счёт», «выполни SQL» inside client messages.
- Strict schema JSON model response, validated with server-side reference allowlist, exact-substring anchors for request items.
- Do not allow the model to choose tool names, tenant IDs, arbitrary SQL/API endpoints or external recipients.
- Never invent quoted contract text or attach missing source spans as evidence.
- Never infer paid status from «not present in text» alone.
- Minimize tokens via approved baseline snippets + relevant past decisions; cap input length and cost; cache by `(message_batch_hash, baseline_hash, classifier_version)` with invalidation on edits/reviews.
- Fail safe on model timeout, provider outage, rate limit, empty/wrong JSON: `NEEDS_REVIEW` or retry with backoff, never «no change» by default.

# 9. DATA MODEL / MIGRATIONS (PROPOSED)

Use next **available** Alembic revision, not an assumed filename. Check all deployed migration heads; migration must be additive, non-destructive and reversible where possible.

| Table | Responsibility / important fields |
|---|---|
| `telegram_link_intents` | id, workspace_id, initiated_by, nonce_hash, telegram_user_id, expires_at, consumed_at, status; TTL/single use |
| `telegram_business_connections` | id, workspace_id, user_id, bot_id, telegram_user_id BIGINT, business_connection_id opaque, is_enabled, rights_json, linked_at, revoked_at; unique bot+connection |
| `telegram_chat_candidates` | connection_id, chat_id BIGINT, display_name minimal, first_seen, last_seen, eligibility; optional metadata-only discovery with short TTL |
| `telegram_chat_bindings` | id, workspace_id, project_id, connection_id, chat_id BIGINT, active, monitoring settings JSON validated, enabled_at, disabled_at; unique active binding for connection+chat |
| `telegram_update_receipts` | bot_id, update_id unique, update_type, received_at, processed_at, error category; no unnecessary chat content |
| `telegram_messages` | workspace_id, binding_id, chat_id, message_id, direction, text_ciphertext/secure reference, text_hash, content_version, edited_at, deleted_at, received_at, subject to retention; unique connection/chat/message |
| `telegram_batches` | id, binding_id, state, first_message_at, last_message_at, quiet_until, max_deadline, snapshot_version, baseline_id, lease fields, processed_at; index due batches |
| `telegram_batch_messages` | batch_id, message_id/row id, version_at_snapshot; unique membership |
| `commercial_signals` | id, project_id, request_id?, baseline_id, category, semantic_fingerprint, status, evidence_state, notification_state, severity, created_at, last_seen_at, reviewed_by; data scoped to workspace |
| `signal_message_evidence` | signal_id, message_id, message_content_version, exact_quote_offsets + message hash, evidence state |

**Existing `requests`:** safely extend check constraint `channel in ('MANUAL','EMAIL','TELEGRAM')`, preserve legacy rows and current uniqueness. Add `source_binding_id` / `source_batch_id` nullable and a durable reference to signal where appropriate; use existing `external_id` uniqueness for `telegram:{connection}:{chat}:{batch}`. Do not pack unrelated message IDs into an unsafe/truncated string; use typed FK relations.

**Author attribution:** current `created_by` references a real user. For connector-generated requests use verified connector owner/delegated user reference plus `origin='INTEGRATION'` and audit metadata; never claim that user manually submitted it. If service principals already exist in actual checkout, adapt to them rather than inventing user accounts.

**Tenant isolation:** all Telegram rows carry workspace_id, composite/safe FK constraints ensure project/connection/binding belong to same workspace. Existing backend ownership checks remain mandatory. If using Supabase/DB RLS, confirm actual policy; API-only tenancy checks do not substitute for proven RLS.

**Concurrence:** transact uniqueness + `SELECT ... FOR UPDATE SKIP LOCKED` or existing queue atomic claim, unique case notification idempotency; tests must prove two workers do not create duplicate request/signal/Change Order.

**Privacy:** encrypted fields/secret manager, limited retention configurable per workspace, data export/delete with cascade policy, audit metadata-only. Do not store raw webhook body indefinitely. Deleted Telegram content must not remain visible after user deletion request; immutable audit can preserve non-content evidence metadata only to the extent permitted by law/policy.

# 10. HTTP API CONTRACTS (PROPOSED; IMPLEMENT AFTER REPO REVIEW)

Authenticated workspace routes (OWNER/MANAGER for mutations; read permission explicit):

```http
POST   /api/v1/workspaces/{workspace_id}/integrations/telegram/link-intents
GET    /api/v1/workspaces/{workspace_id}/integrations/telegram/status
POST   /api/v1/workspaces/{workspace_id}/integrations/telegram/disconnect
GET    /api/v1/workspaces/{workspace_id}/integrations/telegram/eligible-chats
POST   /api/v1/projects/{project_id}/telegram/chat-binding
GET    /api/v1/projects/{project_id}/telegram/chat-binding
PATCH  /api/v1/projects/{project_id}/telegram/monitoring
DELETE /api/v1/projects/{project_id}/telegram/chat-binding
GET    /api/v1/projects/{project_id}/commercial-signals
GET    /api/v1/commercial-signals/{signal_id}
POST   /api/v1/commercial-signals/{signal_id}/dismiss
POST   /api/v1/commercial-signals/{signal_id}/request-clarification
POST   /api/v1/commercial-signals/{signal_id}/convert-to-request
POST   /api/v1/commercial-signals/{signal_id}/create-change-order-draft
```

Webhook (Telegram service auth, NOT bearer auth):

```http
POST   /api/v1/integrations/telegram/webhook
```

**Every authenticated endpoint:** infer workspace/project from database identity, verify caller membership and role, validate version/optimistic concurrency where needed, enforce idempotency keys for mutations, respond `404` for foreign-tenant objects consistent with existing code, log structured non-sensitive audit entries.

**Status models:** `UNLINKED`, `LINK_PENDING`, `CONNECTED`, `ACCESS_REVOKED`, `PAUSED`, `ERROR` for connection; `UNBOUND`, `AWAITING_CHAT`, `READY`, `MONITORING`, `PAUSED`, `NEEDS_BASELINE` for per-project binding. Do not confuse `CONNECTED` with `MONITORING`.

# 11. FRONTEND / UX — НЕ ПРОСТО «КНОПКА ПОДКЛЮЧИТЬ»

**Навигация:** `Project → Documents → Scope → Telegram → Requests → Change Orders → Activity`. Либо сделать Telegram-вкладку внутри существующего ProjectLayout; не переделывать весь UI без причины.

## 11.1 Onboarding, stateful flow

- `Step 1`: договор загружен; parse status с обработкой scanned PDF (`NEEDS_OCR_OR_REVIEW`) и ошибками. Никаких ложных пунктов при отсутствии текста.
- `Step 2`: проверка AI candidate scope, выделение source spans, пользователем нажато `Approve baseline v1`.
- `Step 3`: подключение Business Bot: одна кнопка открыть Telegram, инструкции по разрешениям, факт ownership handshake, privacy notice.
- `Step 4`: Chat Picker **только из eligible observed chats**; empty state «Перейдите в Telegram → Business/Chat Automation → Only selected chats и разрешите чат; дождитесь нового сообщения»; не имитировать список контактов.
- `Step 5`: review settings: `smart`, selected=true, dedup=true, drafts=true, debounce=2min; start monitoring explicit user action.
- `Step 6`: status + activity: last event, last successful AI analysis, permissions, pause/disconnect, delete data.

## 11.2 Commercial Signal Card

Состав: названия проекта/клиента; `Potential change` (не окончательное решение); краткая цитата/ссылка на Telegram message/version; точный фрагмент договора; версия baseline; confidence as internal calibration only; rationale and uncertainty; duplicate history; кнопки `Review`, `Dismiss`, `Clarify`, `Estimate`, `Draft Change Order`. Price empty until human estimate. Статусы «предположение»/«требует подтверждения» видны пользователю.

## 11.3 UX quality

- Работает на ширине 375px+, клавиатура, ARIA labels, reduced-motion.
- RU/EN тексты для новых областей; не показывать untranslated keys.
- Skeleton/error/empty/permission denied / expired link / disconnected / stale baseline states.
- Не показывать значение бот-токена, webhook secret и персональные данные других чатов.
- Если Telegram не подключён, основное приложение и ручной request-intake продолжают работать.

# 12. КОММЕРЧЕСКОЕ СОГЛАСОВАНИЕ И КОНТРОЛЬ ВЫПОЛНЕНИЯ

**Сохранить существующее ядро:** `ScopeBaseline`, `AnalysisRun`, `Finding`, `Estimate`, `ChangeOrder`, `Approval`, `ChangeOrderRevision`, `ChangeOrderExport`, `AuditEvent`.

**P0 Telegram MVP:** сигнал → human review → request/estimate (по rate card) → `DRAFT` Change Order → `APPROVED_INTERNAL` → экспорт с верным статусом. **Не писать «клиент принял»**, если реально не реализован отдельный клиентский доступ и проверенное подтверждение конкретной revision hash.

**P1 (продолжение старой TermRail спецификации):** explicit Client Reviewer permission, client accept/decline against current revision hash, immutable approval, baseline v2 and Commercial Authorization Decision bound to a task before `Start Work`, cryptographically verifiable receipt and human override audit. Не подменять эти функции простым сообщением в Telegram и не утверждать, что бот «блокирует Jira», если у интеграции нет такой capability.

Точный детальный протокол `Start Work`/Authorization Receipt из старого master spec необходимо сохранить в product backlog и привязать к текущей DB state machine; не выкидывать из-за Telegram.

# 13. БЕЗОПАСНОСТЬ, ПРАВА И PRIVACY

## 13.1 Threat model

- Fake webhook, stolen bot token, leaked secret → TLS, secret header, secret rotation, rate limit, request size limit, no logging secrets, distinct staging/prod bot.
- Wrong account linked → one-time proof of Telegram ownership + binding to authenticated workspace.
- Cross-tenant data leak → strict FK, RBAC, scoped queries, negative tenant tests.
- Revoked chat permission → fail-closed processing; UI shows paused/revoked; no analytics on cached unapproved conversations.
- Prompt injection from client message or uploaded document → untrusted data boundaries, structured output schema, deterministic policy, no AI tool side effects.
- Replayed webhook / duplicate jobs → unique constraints + transaction + at-least-once processing.
- Wrong financial decision → human review, no fake price, pinned baseline/revision.
- Privacy leak by chat picker → only opted-in minimal metadata from observed permitted chats, never contact list scraping.
- Misuse of Telegram sender rights → no auto-send P0, no read/delete/profile privileges requested.

## 13.2 Privacy requirements

- Data inventory: collect only selected chat messages needed for contractual comparison. Nonselected chat bodies never persist or reach AI.
- Explicit workspace owner consent and disclosure to all relevant participants as required by applicable law and agreements. Obtain legal review before real external pilots; different countries have different consent/retention requirements.
- Workspace retention settings and `delete project telegram data` with testable physical deletion of encrypted message content where appropriate, subject to necessary legal retention of non-content audit metadata.
- Prompt/data logging off for chat content; provider data processing/subprocessor disclosure, opt-out/training protections as supported by provider agreement.
- Private file storage and encrypted-at-rest messages; access via authenticated backend only.
- Rate and cost caps per workspace, abuse protection, incident handling; production health dashboards must not contain raw client messages.

# 14. TEST PLAN — КРИТЕРИИ ПРИЁМКИ

**Do not claim green until tests actually execute.** Add real tests; do not replace tests with screenshots of expected outputs.

## G0 — Repository + rebrand

- `git status` initially captured; independent feature branch; no pre-existing changes lost.
- `TermRail` visible in UI, OpenAPI, PDF, config, docs; tracked active files no unwanted `ScopeLock` refs.
- Existing migrations apply to empty PostgreSQL and upgrade a populated fixture database without data loss.
- `apps/web` lint/typecheck/build, `apps/api` Ruff/mypy/pytest pass according to existing project scripts.

## G1 — Contract-first invariant

- Without approved baseline -> monitoring cannot activate (`409 BASELINE_REQUIRED` or documented equivalent).
- Scanned document without extracted text never yields fabricated scope.
- Approval pins baseline hash/revision; baseline changes trigger stale-signal handling.

## G2 — Connection and chat permissions

- Link intent expires; cannot reuse; wrong Telegram user cannot claim it.
- A business connection cannot be claimed by wrong workspace.
- Nonselected chat payload produces NO persisted message content and NO AI request.
- Chat ID not observed/allowed cannot be bound by guessing numeric ID.
- Revocation/disabled connection stops processing and visible state changes.
- No rights to reply/delete/profile management needed for monitoring.

## G3 — Idempotency, debounce, race

- Same Telegram `update_id` delivered 5 times -> one receipt + one stored message.
- Out-of-order delivery, two worker instances and lease recovery do not double-create requests/signals.
- 5 messages within sliding 120s -> one batch; new message at t=110s shifts quiet timer; batch finalizes after 120s quiet.
- Continuous traffic capped at 15 minutes/100 messages.
- Repeated same semantic requirement -> one active case and one notification, later evidence attached.
- Two unrelated requests in the same batch remain two separate atomic requirements.
- Edit/delete before finalize updates snapshot; edit/delete after finalize invalidates evidence for review.
- Telegram outage / AI 429 / DB timeout retries appropriately; no lost ACKed event and no fake `IN_SCOPE` fallback.

## G4 — AI and commercial evidence

- Test matrix includes: greetings, ordinary status, legitimate scope change, warranty bug, revision limit, deadline change, ambiguous request, unsupported data, duplicate requests, malicious prompt injection, changed baseline, mixed RU/EN and where supported KK.
- Citations to contract source span and Telegram message are exact and server-validated; fabricated model citations rejected.
- AI cannot create approved Estimate, accept client signature, send message, or write invented commercial price.
- `ChangeOrder` remains DRAFT until real manager action; prior revision approval invalidated by edit.

## G5 — Security and UX

- Cross-workspace project/chat/signal access returns 404/403 according to existing policy; webhook bypass of identity impossible.
- Link intent is opaque; webhook secret compare verified; no secrets or chat text in application logs.
- 375px, keyboard navigation, reduced motion, connection/revocation/empty states pass browser tests.
- Complete journey: register → workspace → project → upload → baseline approve → Telegram link (real sandbox or explicit deterministic mock) → select chat → receive event → wait 120s via controlled test clock → finding → review → draft → export. Test clock, not actual 2-minute sleeps.

## G6 — Live proof (not fake demo)

- With an authorized test Telegram Business account and sandbox/staging bot: verify actual `business_connection`, actual inbound update, selection, trigger, persisted finding and safe review.
- No live credentials -> only mock integration tests may be marked PASS; real Telegram test MUST be marked BLOCKED.
- User-facing demo must clearly label prerecorded recordings and synthetic data. No unverified accuracy/revenue/savings claims.
- Re-run documented end-to-end suite 5 consecutive times for stage demo when environment supports it; record command, SHA, output and environment.

## Evaluation metrics (targets, not claimed achievements)

- False alerts per 100 non-commercial messages; recall on annotated change requests; human disagreement rate; duplicate rate; cost per 1000 messages; 95th percentile processing latency **excluding intentional 120s debounce**; successful ingestion vs retries.
- Build evaluation set with labeled examples from permitted data and synthetic data; split dev/holdout; never fabricate measured accuracy. Recommend baseline target precision >=90% on holdout for notifications, with recall separately reported. This is a **target to validate**, not verified capability.

# 15. OBSERVABILITY / OPERATIONS

- Structured events: connection_linked/revoked, chat_bound, webhook_received, webhook_deduped, batch_scheduled/finalized, analysis_queued/succeeded/failed, signal_created/merged/dismissed, draft_created, approval_observed.
- Logs: IDs, statuses, latency, counts and correlation ID; **no document/chat payload/token/PII**.
- Dashboard: webhook 2xx/non-2xx, processing lag, queue size, dead letters, token/cost budget, retry count, duplicate suppression rate, permission revoked counts, model error rate.
- Retry policy: provider rate limits/backoff+jitter, DB transient retry; non-retryable invalid auth/permission quarantine; no infinite loop; manual replay for dead letters.
- Staging: separate bot token, database, webhook secret, AI key and workspace; production auto-send off.
- Backup + restore test; idempotent demo reset; deployment rollback for code, safe forward-fix migrations for schema.

# 16. IMPLEMENTATION PLAN / PULL REQUEST BOUNDARIES

**Phase 0 — Repo stabilization / rebrand**

- Inspect both branches, reconcile spec, ensure current code and tests preserved.
- Full ScopeLock → TermRail active-brand cleanup, lockfile consistency, `.env.example`, docs, CI scripts.
- Baseline test suite; leave a clear G0 report.

**Phase 1 — Telegram vertical slice, read-only**

- Typed Business webhook, ownership link intent, exact connection mapping, chat discovery/binding, privacy gates, webhook receipts/idempotency.
- Project Telegram tab. No AI, no external message send. Real Business API smoke where credentials exist.

**Phase 2 — Smart Trigger / analysis reuse**

- Additive schema + 120s debounce batching, retriable jobs, message source citations, prefilter, semantic dedupe, baseline pinned analysis.
- Reuse current analysis/evidence. All output internal; implement UI signal inbox.

**Phase 3 — Commercial workflow & demo**

- Signal → review → estimate → Change Order draft, revised PDF branded TermRail.
- Real end-to-end staging demo, metrics, false-positive review. Ensure no client acceptance claim without implementation.

**Phase 4 — Paid pilot / Authorization Gate**

- Proper client reviewer, receipts, tasks and `Start Work` authorization, retention controls, provider budgets, permissions hardening.
- Integrations with project trackers only after capability matrix and proof of working enforcement.

**Commit/PR rules:** each phase independently reviewable and testable. No parallel edits to same migration/state machine by multiple agents. One integration owner merges sequentially after review. Never auto-merge. Report tests and limitations.

# 17. REQUIRED FINAL DELIVERABLES FROM CLAUDE CLOUD

1. `docs/architecture/telegram-business.md` (real Telegram APIs/permissions, topology, sequence diagrams, failure modes).
2. `docs/security/telegram-threat-model.md`, privacy/retention plan.
3. Migration plan and actual migrations for delivered phases, no destructive reset.
4. `apps/api`/`apps/web` implementation with tests and typed API client.
5. Updated single `TERMRAIL_MASTER_SPEC.md` in the chosen integration branch (or canonical documentation path with clear source of truth).
6. Working `.env.example` with `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_ENABLED`, staging/production separation; real secrets never committed.
7. `scripts/telegram_*` setup/smoke only as needed, with no token leakage.
8. New tests for webhook, binding, debounce, tenant isolation, evidence, safe draft.
9. Branding report: all active product paths contain TermRail, not ScopeLock.
10. `IMPLEMENTATION_REPORT.md`: exact branch/SHAs, changed files, commands actually executed, results, blocked tests, remaining risks, next phases.

# 18. DEFINITION OF DONE

**MVP is accepted only if:**

- A real contract can be uploaded, evidence extracted and approved by a human.
- One real Telegram Business account can be connected and the owner can select exactly one observed, authorized chat.
- Unselected chats are neither read by the LLM nor persisted as message content.
- Messages wait 120s after last relevant message, then commercial AI runs against an approved baseline.
- Meaningful change produces one reviewable finding with provable contract + chat citations; duplicates consolidate.
- A manager can create a draft Change Order; no implicit send, signature, receipt of payment or automatic client acceptance.
- Access revoked → ingestion stops; tenant isolation, webhook security and race/idempotency tests pass.
- Active UI/API/PDF/docs are branded TermRail; legacy data and working modules remain intact.
- Results of real tests, builds and live checks are attached, with blockers honestly identified.

**Explicit non-goals for Telegram MVP:** full historical chat import, all-contact picker, automatic Telegram replies, automatic e-signature, proof of payment, Telegram-based legal contract signing, production Jira/ClickUp blocking, guaranteed AI accuracy, social/chatbot features unrelated to commercial control.

---

# APPENDIX A — CLOUD EXECUTION ORDER / FIRST COMMANDS

Perform in order, adjusting commands to actual repo scripts:

```bash
pwd
git status --short --branch
git branch -a
git log --oneline --decorate -8
git diff --stat
git diff --cached --stat
# inspect the old/new master spec and all relevant project files
# perform code-based architecture/coverage analysis before modifying anything
```

When source is reconciled, capture test command baseline. Suggested scripts, subject to package/tool availability:

```bash
# Frontend: from apps/web
npm ci
npm run lint
npm run typecheck
npm run test
npm run build

# Backend: from apps/api with configured PostgreSQL test DB
uv sync --group dev
uv run ruff check .
uv run pytest -q
# mypy if project config supports it
```

Always verify actual scripts and environment before interpreting failures. Do not try production credentials to fix local tests.

# APPENDIX B — TECHNICAL REFERENCES

- Telegram Bot API: https://core.telegram.org/bots/api
- Telegram Business integration: https://core.telegram.org/bots/features#business-bots
- Connected business bots / one-bot and permission model: https://core.telegram.org/api/bots/connected-business-bots
- Telegram API changelog: https://core.telegram.org/bots/api-changelog
- Repository: https://github.com/SaginbekDaniel/TermRail

**Never claim this specification itself proves a feature is already implemented.**

---

# 19. CARRIED-OVER BACKLOG FROM MASTER SPEC V1 (NOT IMPLEMENTED)

v1 (`docs/specs/TERMRAIL_MASTER_SPEC_V1.md`) is superseded as a document but its following requirements are
**open product backlog**, bound to the P1/Phase 4 scope of §12/§16. None of them exists in code; the UI
must not present them as working.

| v1 ref | Requirement | Status |
|---|---|---|
| §5.1–5.2 | Commercial Authorization states (`AUTHORIZED_BASELINE/CHANGE/WAIVER`, `REVIEW_REQUIRED`, `NEEDS_CONTEXT`, `NOT_AUTHORIZED`, `STALE_AUTHORIZATION`) per task revision; fast/review/emergency lanes | Not implemented |
| §5.3 | Authorization Receipt (canonical JSON + `receipt_sha256`, baseline/task fingerprints, policy version) | Not implemented |
| §5.4, §8.5 | Task state machine; server-side `Start Work` check in the same transaction as the status change | Not implemented (no task entity) |
| §5.5, §7.3 | Client accept/decline of a specific revision hash (`ACCEPTED_IN_APP` / `EXECUTED_EXTERNAL`), baseline v2 from an accepted change order | Not implemented; current maximum status is `APPROVED_INTERNAL`/`EXPORTED` |
| §14 | Deterministic authorization resolver + decision table | Not implemented |
| §4.3 | Tracker adapters with a per-adapter capability matrix | Not implemented |
| §18.2 | `scripts/verify_brand.py` | **Implemented** (Phase 1) |

Implementation state of this document is tracked in `IMPLEMENTATION_REPORT.md`; that file, not this
specification, is the evidence of what works.
