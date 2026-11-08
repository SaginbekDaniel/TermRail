# Telegram connector — threat model, privacy and retention

Scope: the read-only Telegram Business connector and commercial signals. Each control below names where it
is enforced and which automated test covers it (`apps/api/tests/test_telegram_*.py`).

## Assets

Client chat message bodies; the mapping workspace ↔ Telegram account; bot token, webhook secret, data key;
commercial decisions (signals, estimates, change-order drafts); tenant isolation.

## Threats and controls

| Threat | Control | Where | Test |
|---|---|---|---|
| Forged webhook | `X-Telegram-Bot-Api-Secret-Token` compared with `hmac.compare_digest`; route 404 when disabled; 20 bad attempts/min/IP → 429 | `telegram_webhook.py` | `test_webhook_requires_secret`, `test_webhook_hidden_when_disabled` |
| Oversized / malformed body | streaming size cap (256 KiB) before parsing; typed validation | same | `test_webhook_rejects_oversized_and_malformed` |
| Replay / duplicate delivery | unique `(bot_id, update_id)` receipt in the same transaction; unique message key | `ingress.py` | `test_same_update_delivered_five_times_is_processed_once` |
| Linking someone else's Telegram | one-time nonce (sha256 stored, 10 min, single use) proves Telegram user id; claim requires `business_connection.user.id` equality; no manual connection ids | `linking.py` | `test_link_intent_is_single_use_and_expires`, `test_wrong_telegram_user_cannot_claim` |
| Hijacking a tenant's connection | live connections never move; conflict state; re-link after disconnect creates a fresh row | `linking.py` | `test_connection_cannot_be_claimed_by_another_workspace`, `test_disconnected_connection_moves_to_new_workspace_without_history` |
| Cross-tenant access | API: membership check, foreign objects → 404. DB: composite `(id, workspace_id)` FKs on every Telegram table | `deps.py`, models, migration 0004 | `test_cross_tenant_access_is_404`, `test_db_rejects_cross_tenant_binding` |
| Reading unselected chats | bodies persisted only for bound + monitored chats; others keep metadata only; no AI call | `ingress.py` | `test_unselected_chat_is_never_stored_or_analysed` |
| Guessing a chat id into monitoring | binding requires a candidate observed through this connection | `bindings.py` | `test_chat_id_cannot_be_guessed_into_monitoring` |
| Revoked access still processed | `is_enabled=false` → revoke, monitoring off, open batch cancelled and erased; finalize re-checks all conditions | `linking.py`, `batching.py` | `test_revocation_stops_ingestion_and_purges_buffer`, `test_baseline_removed_from_conditions_fails_closed` |
| Prompt injection in chat | chat text is untrusted data in the existing prompts; strict schema; server ref allowlist; no tools/side effects | existing `llm/prompts.py`, `evidence.py` | `test_prompt_injection_is_data_not_instructions` |
| Fabricated evidence | contract refs validated server-side; chat citations derived from offsets, re-verified by hash on read | `evidence.py`, `signals.py` | `test_change_bug_and_noise_in_one_batch`, `test_edit_and_delete_after_finalize_invalidate_evidence` |
| Wrong financial decision | no price without approved estimate; drafts only; optimistic versions on every action | `signals.py` | `test_signal_to_change_order_draft` |
| Privilege misuse | link/bind/monitor/act require OWNER/MANAGER | `api/v1/telegram.py` | `test_only_managers_can_link`, `test_viewer_cannot_act_on_signals` |
| Data at rest leak | Fernet encryption of bodies (`TELEGRAM_DATA_KEY`, rotation via key list) | `crypto.py` | `test_message_bodies_are_encrypted_at_rest_and_never_logged` |
| Content in logs | logs carry ids/types/outcome codes only; audit metadata never stores text | `telegram_webhook.py`, `audit.py` | same test (caplog) |
| Abuse of send rights | no send method exists; `ALLOW_EXTERNAL_SEND=true` refuses to start | `config.py` | existing config validation |

## Not covered by this slice (operator responsibilities / next steps)

- TLS termination, global rate limiting and WAF in front of the webhook (infrastructure).
- Secret manager integration; secrets come from the environment today. Use distinct bot, secret and data
  key per environment.
- The in-process bad-secret throttle is per API process, not global.
- Webhook source IP allowlisting (Telegram's published ranges) is not enforced.
- Key rotation re-encryption job (old keys stay in the list until bodies expire by retention).

## Privacy

- **Data minimisation:** only the chat explicitly bound to a project is read; for other allowed chats only
  id, display name and timestamps are kept. No history import, no attachments, no voice/video/OCR.
- **Consent:** monitoring cannot start without the manager confirming that the client was informed and that
  processing is permitted. **Legal review per jurisdiction is required before real external pilots.**
- **Retention:** bodies erased after `TELEGRAM_MESSAGE_RETENTION_DAYS` (default 90) by the retention command
  (schedule it daily); erased immediately on Telegram deletion, revocation of un-analysed batches,
  disconnect, and "Delete stored messages".
- **Known gap:** requests already created from chat text (`requests.message_text`, request items, finding
  summaries, change-order snapshots) are part of the commercial record and are **not** erased by
  "Delete stored messages" or retention. This needs a product/legal decision (redaction vs. retention of
  commercial records) before external pilots.
- **AI provider:** chat text that passes the prefilter is sent to the configured AI provider. Use a provider
  tier whose terms exclude training on customer data (see v1 spec §12.5 on free tiers).
