import uuid
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from pydantic import BaseModel


class BlueBubblesError(Exception):
    pass


class InboundMessage(BaseModel, frozen=True):
    guid: str
    chat_guid: str
    sender_address: str | None
    text: str
    is_from_me: bool
    is_group: bool
    sent_at: datetime
    #: The GUID of the message this one is an inline reply to -- the thread's
    #: root, which iMessage keeps pointing at the first message of the thread
    #: for every reply in it. ``None`` for a message that replies to nothing.
    thread_originator_guid: str | None = None
    #: The file names of any attachments, as BlueBubbles reports them. Read so a
    #: crashed attachment send can be reconciled by name, never for content.
    attachment_names: tuple[str, ...] = ()


def _record_to_message(record: dict) -> InboundMessage | None:
    chats = record.get("chats") or []
    chat_guid = record.get("chatGuid") or (chats[0].get("guid") if chats else None)
    if not chat_guid or not record.get("guid"):
        return None
    if _is_reaction(record):
        # A tapback arrives as a message whose text is the reaction word plus the
        # whole quoted original ("Liked “🚨 Trade alert …”"), so it reads exactly
        # like a repost of the alert. It is not a message anyone wrote; nothing
        # downstream should ever see it.
        return None
    handle = record.get("handle") or {}
    created = record.get("dateCreated") or 0
    attachments = record.get("attachments") or []
    return InboundMessage(
        guid=record["guid"],
        chat_guid=chat_guid,
        sender_address=handle.get("address"),
        text=record.get("text") or "",
        is_from_me=bool(record.get("isFromMe")),
        is_group=bool(record.get("isGroup")) or ";+;" in chat_guid,
        sent_at=datetime.fromtimestamp(created / 1000, tz=UTC),
        thread_originator_guid=(
            record.get("threadOriginatorGuid") or record.get("replyToGuid") or None
        ),
        attachment_names=tuple(
            a.get("transferName") for a in attachments if a.get("transferName")
        ),
    )


def _is_reaction(record: dict) -> bool:
    """BlueBubbles marks a tapback with the guid it reacts to and a type: the
    iMessage numeric codes (2000-2005 add, 3000-3005 remove, 2006/3006 the
    custom-emoji kind) or, on newer servers, a word such as ``like``."""
    if record.get("associatedMessageGuid"):
        return True
    kind = record.get("associatedMessageType")
    return bool(kind) and kind not in (0, "0")


def parse_webhook(payload: dict) -> InboundMessage | None:
    if payload.get("type") != "new-message":
        return None
    return _record_to_message(payload.get("data") or {})


class BlueBubblesClient:
    def __init__(self, server_url: str, password: str, http: httpx.Client) -> None:
        self._base = server_url.rstrip("/")
        self._password = password
        self._http = http

    def _request(self, method: str, path: str, **kwargs) -> dict:
        params = dict(kwargs.pop("params", {}) or {})
        params["password"] = self._password
        try:
            response = self._http.request(
                method,
                f"{self._base}{path}",
                params=params,
                timeout=15.0,
                **kwargs,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            msg = f"{method} {path} failed: {exc.__class__.__name__}"
            raise BlueBubblesError(msg) from exc
        return response.json()

    def ping(self) -> bool:
        try:
            return self._request("GET", "/api/v1/ping").get("data") == "pong"
        except BlueBubblesError:
            return False

    def server_info(self) -> dict:
        return self._request("GET", "/api/v1/server/info").get("data") or {}

    def chat_participants(self, chat_guid: str) -> list[str]:
        data = (
            self._request(
                "GET",
                f"/api/v1/chat/{quote(chat_guid, safe='')}",
                params={"with": "participants"},
            ).get("data")
            or {}
        )
        return [p.get("address") for p in data.get("participants") or [] if p.get("address")]

    def messages_after(
        self, chat_guid: str, after: datetime, limit: int = 100
    ) -> list[InboundMessage]:
        params = {
            "after": str(int(after.timestamp() * 1000)),
            "sort": "ASC",
            "limit": str(limit),
            # A message query carries attachments only when it asks for them, and
            # a crashed attachment send is reconciled by the file's name.
            "with": "handle,attachment",
        }
        data = (
            self._request(
                "GET",
                f"/api/v1/chat/{quote(chat_guid, safe='')}/message",
                params=params,
            ).get("data")
            or []
        )
        return [m for m in (_record_to_message(r) for r in data) if m]

    def send_text(self, chat_guid: str, text: str) -> str:
        body = {
            "chatGuid": chat_guid,
            "tempGuid": uuid.uuid4().hex,
            "message": text,
        }
        data = self._request("POST", "/api/v1/message/text", json=body).get("data") or {}
        guid = data.get("guid")
        if not guid:
            raise BlueBubblesError("send returned no message guid")
        return guid

    def send_attachment(
        self, chat_guid: str, filename: str, data: bytes, mime: str = "text/html"
    ) -> str:
        """Send one file to a chat. Multipart, and no Private API needed.

        The `name` form field is what iMessage shows as the file's name, so it
        is the artifact's own name and never a temp name.
        """
        fields = {
            "chatGuid": chat_guid,
            "tempGuid": uuid.uuid4().hex,
            "name": filename,
        }
        files = {"attachment": (filename, data, mime)}
        data_out = self._request(
            "POST", "/api/v1/message/attachment", data=fields, files=files
        ).get("data") or {}
        guid = data_out.get("guid")
        if not guid:
            raise BlueBubblesError("attachment send returned no message guid")
        return guid

    def ensure_webhook(self, url: str) -> None:
        existing = self._request("GET", "/api/v1/webhook").get("data") or []
        if any(w.get("url") == url for w in existing):
            return
        self._request("POST", "/api/v1/webhook", json={"url": url, "events": ["new-message"]})
