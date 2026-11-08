"""Retention: physically erase stored Telegram message bodies older than TELEGRAM_MESSAGE_RETENTION_DAYS.

Run daily from a scheduler (cron, platform job):  python -m app.integrations.telegram.retention
Only message text is erased; ids, hashes and timestamps stay for the audit trail. Messages still waiting in
an OPEN batch are never touched (they are erased anyway if that batch is cancelled). Evidence that cited an
erased message is marked REVOKED so no reader is shown a quote that no longer exists.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import get_settings
from app.db.models import CommercialSignal, SignalMessageEvidence, TelegramBatch, TelegramBatchMessage, TelegramMessage

log = logging.getLogger("termrail.telegram.retention")


async def purge_expired(session: AsyncSession) -> int:
    cutoff = utcnow() - timedelta(days=get_settings().telegram_message_retention_days)
    in_open_batch = exists().where(
        TelegramBatchMessage.message_row_id == TelegramMessage.id,
        TelegramBatchMessage.batch_id == TelegramBatch.id,
        TelegramBatch.state == "OPEN",
    )
    ids = list(
        (
            await session.scalars(
                select(TelegramMessage.id).where(
                    TelegramMessage.received_at < cutoff,
                    TelegramMessage.text_ciphertext.is_not(None),
                    ~in_open_batch,
                )
            )
        ).all()
    )
    if not ids:
        return 0
    now = utcnow()
    await session.execute(
        update(TelegramMessage).where(TelegramMessage.id.in_(ids)).values(text_ciphertext=None, purged_at=now)
    )
    signal_ids = select(SignalMessageEvidence.signal_id).where(SignalMessageEvidence.message_row_id.in_(ids))
    await session.execute(
        update(SignalMessageEvidence)
        .where(SignalMessageEvidence.message_row_id.in_(ids), SignalMessageEvidence.state != "REVOKED")
        .values(state="REVOKED")
    )
    await session.execute(
        update(CommercialSignal).where(CommercialSignal.id.in_(signal_ids)).values(evidence_state="REVOKED")
    )
    await session.commit()
    log.info("telegram_retention_purged", extra={"messages": len(ids)})
    return len(ids)


def main() -> None:
    from app.core.logging import configure_logging
    from app.db.session import dispose_engine, get_sessionmaker

    configure_logging()

    async def run() -> None:
        async with get_sessionmaker()() as s:
            await purge_expired(s)
        await dispose_engine()

    asyncio.run(run())


if __name__ == "__main__":
    main()
