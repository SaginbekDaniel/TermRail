"""Typed subset of the Telegram Bot API Update object (https://core.telegram.org/bots/api#update).

Only fields TermRail uses are modelled; unknown fields are ignored. Business updates
(business_connection / business_message / edited_business_message / deleted_business_messages) are kept
separate from ordinary `message`, which is used only for the /start ownership handshake.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TgUser(_Model):
    id: int
    is_bot: bool = False
    first_name: str = ""
    last_name: str | None = None
    username: str | None = None


class TgChat(_Model):
    id: int
    type: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    title: str | None = None

    @property
    def display_name(self) -> str:
        if self.title:
            return self.title[:200]
        name = " ".join(p for p in (self.first_name, self.last_name) if p)
        if self.username:
            name = f"{name} (@{self.username})" if name else f"@{self.username}"
        return name[:200]


class TgMessage(_Model):
    message_id: int
    date: int
    chat: TgChat
    from_: TgUser | None = Field(default=None, alias="from")
    business_connection_id: str | None = None
    text: str | None = None
    caption: str | None = None
    edit_date: int | None = None
    # Any media we do not read in P0 (photos, voice, video, documents, stickers...).
    photo: list[Any] | None = None
    document: dict[str, Any] | None = None
    voice: dict[str, Any] | None = None
    video: dict[str, Any] | None = None
    video_note: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None
    sticker: dict[str, Any] | None = None
    animation: dict[str, Any] | None = None

    @property
    def readable_text(self) -> str:
        return (self.text if self.text is not None else self.caption) or ""

    @property
    def has_media(self) -> bool:
        return any(
            v is not None
            for v in (
                self.photo,
                self.document,
                self.voice,
                self.video,
                self.video_note,
                self.audio,
                self.sticker,
                self.animation,
            )
        )


class TgBusinessConnection(_Model):
    id: str
    user: TgUser
    user_chat_id: int | None = None
    date: int
    is_enabled: bool
    # Current schema: `rights` (BusinessBotRights). Legacy `can_reply` is accepted but never required.
    rights: dict[str, Any] | None = None
    can_reply: bool | None = None


class TgBusinessMessagesDeleted(_Model):
    business_connection_id: str
    chat: TgChat
    message_ids: list[int]


class TgUpdate(_Model):
    update_id: int
    message: TgMessage | None = None
    business_connection: TgBusinessConnection | None = None
    business_message: TgMessage | None = None
    edited_business_message: TgMessage | None = None
    deleted_business_messages: TgBusinessMessagesDeleted | None = None

    @property
    def kind(self) -> str:
        for name in (
            "business_connection",
            "business_message",
            "edited_business_message",
            "deleted_business_messages",
            "message",
        ):
            if getattr(self, name) is not None:
                return name
        return "unsupported"


ALLOWED_UPDATES = [
    "message",
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
]
