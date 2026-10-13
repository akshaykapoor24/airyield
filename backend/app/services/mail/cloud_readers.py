"""Reading new mail from Gmail (Gmail API) and Microsoft 365 / Outlook (Microsoft Graph).

Same contract as the IMAP reader: give back raw RFC 5322 bytes for messages from onboarded
senders, oldest first, and leave everything else alone (architecture/03 §3.3–3.4).

GMAIL — strict at the source. `messages.list` takes a Gmail search,
`from:(a@x.in OR @acme.in) after:<t>` (an "@domain" term is a whole company, registry.py), so
mail from anyone else is never even listed. Raw bytes come from `format=raw`.

MICROSOFT — Graph cannot search by a list of senders reliably, so new messages are listed with
ONLY their sender fields selected (from / sender / replyTo), screened against the registry in
memory, and the full message (`/$value`, MIME) is downloaded only for a match. Nothing about a
non-match is stored. `Prefer: IdType="ImmutableId"` keeps a message's id stable when the user
moves it between folders, so a move is not a "new" message.

TIME-BASED CURSOR WITH LOOKBACK. Both read "everything since T", where T is the last check
minus a few days (sync.LOOKBACK_DAYS) — providers index new mail a little late, and the
lookback catches it. Already-stored ids (`existing`) and ids judged not ours (`ignored`) are
skipped, so the overlap costs list calls, not downloads.
"""
from __future__ import annotations

import base64
import calendar
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import httpx

from app.services.mail.oauth import OAuthError

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_MAX_LISTED = 2000          # per check: a runaway guard, not a working limit
_GMAIL_QUERY_CHUNK = 40     # senders per Gmail search; keeps the query well under its length limit
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
GRAPH = "https://graph.microsoft.com/v1.0/me"


class CloudError(Exception):
    """A provider problem worth showing to the user (rate limit, outage, missing mailbox)."""


@dataclass
class CloudFetched:
    provider_id: str                 # "gmail:<id>" / "graph:<immutable id>"
    folder: str                      # INBOX | SPAM | Junk
    internaldate: datetime | None    # naive UTC
    size: int | None
    raw: bytes | None
    too_large: bool = False
    first_sync: bool = False
    uid: int | None = None           # IMAP only; kept so sync.py treats every reader alike


@dataclass
class CloudRead:
    messages: list[CloudFetched] = field(default_factory=list)
    more_waiting: bool = False


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _raise_for(resp: httpx.Response, provider: str) -> None:
    if resp.status_code in (401, 403):
        raise OAuthError(f"FareQube can no longer read this {provider} mailbox. Reconnect it.", reauth=True)
    if resp.status_code == 429:
        raise CloudError(f"{provider} asked us to slow down. New mail will be checked again shortly.")
    if resp.status_code >= 400:
        raise CloudError(f"{provider} answered {resp.status_code}. It may be a temporary problem.")


def _headers_only(raw: bytes) -> bytes:
    cut = raw.find(b"\r\n\r\n")
    if cut == -1:
        cut = raw.find(b"\n\n")
    return raw[: cut + 4] if cut != -1 else raw[:16384]


# ── Gmail ───────────────────────────────────────────────────────────────────

async def gmail_read(access_token: str, *, senders: list[str], after: datetime, include_spam: bool,
                     skip: set[str], limit: int, max_bytes: int, first_sync: bool) -> CloudRead:
    epoch = calendar.timegm(after.timetuple())
    auth = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=auth) as client:
        ids: list[str] = []
        for i in range(0, len(senders), _GMAIL_QUERY_CHUNK):
            chunk = senders[i:i + _GMAIL_QUERY_CHUNK]
            q = f"from:({' OR '.join(chunk)}) after:{epoch}"
            params: dict = {"q": q, "maxResults": 500}
            if include_spam:                      # Gmail search leaves Spam out unless asked
                params["includeSpamTrash"] = "true"
                params["q"] = q + " -in:trash"
            token = None
            while len(ids) < _MAX_LISTED:
                if token:
                    params["pageToken"] = token
                resp = await client.get(f"{GMAIL}/messages", params=params)
                _raise_for(resp, "Gmail")
                body = resp.json()
                ids += [m["id"] for m in body.get("messages", [])]
                token = body.get("nextPageToken")
                if not token:
                    break

        todo = [i for i in dict.fromkeys(ids) if f"gmail:{i}" not in skip]
        # list returns newest first; fetch the cheap envelope to order oldest first and size-check.
        meta = []
        for mid in todo:
            resp = await client.get(f"{GMAIL}/messages/{mid}", params={"format": "minimal"})
            if resp.status_code == 404:
                continue                          # deleted between list and get
            _raise_for(resp, "Gmail")
            m = resp.json()
            meta.append((int(m.get("internalDate", 0)), mid, int(m.get("sizeEstimate", 0)), m.get("labelIds", [])))
        meta.sort()

        out = CloudRead(more_waiting=len(meta) > limit)
        for internal_ms, mid, size, labels in meta[:limit]:
            too_large = size > max_bytes
            resp = await client.get(f"{GMAIL}/messages/{mid}", params={"format": "raw"} if not too_large else
                                    {"format": "metadata", "metadataHeaders": ["From", "Sender", "Reply-To", "To", "Cc",
                                                                               "Subject", "Date", "Message-ID"]})
            if resp.status_code == 404:
                continue
            _raise_for(resp, "Gmail")
            m = resp.json()
            if too_large:
                raw = "".join(f"{h['name']}: {h['value']}\r\n" for h in m.get("payload", {}).get("headers", [])).encode() + b"\r\n"
            else:
                raw = base64.urlsafe_b64decode(m["raw"] + "=" * (-len(m["raw"]) % 4))
            out.messages.append(CloudFetched(
                provider_id=f"gmail:{mid}", folder="SPAM" if "SPAM" in labels else "INBOX",
                internaldate=_utc(datetime.fromtimestamp(internal_ms / 1000, timezone.utc)) if internal_ms else None,
                size=size or len(raw), raw=raw, too_large=too_large, first_sync=first_sync,
            ))
        return out


# ── Microsoft Graph ─────────────────────────────────────────────────────────

def _graph_addresses(m: dict) -> list[str]:
    out = []
    for key in ("from", "sender"):
        addr = ((m.get(key) or {}).get("emailAddress") or {}).get("address")
        if addr:
            out.append(addr.lower())
    for r in m.get("replyTo") or []:
        addr = (r.get("emailAddress") or {}).get("address")
        if addr:
            out.append(addr.lower())
    return out


async def graph_read(access_token: str, *, is_sender: Callable[[str], bool], after: datetime, include_spam: bool,
                     skip: set[str], limit: int, max_bytes: int, first_sync: bool) -> CloudRead:
    headers = {"Authorization": f"Bearer {access_token}", "Prefer": 'IdType="ImmutableId"'}
    since = after.replace(microsecond=0).isoformat() + "Z"
    folders = [("inbox", "INBOX")] + ([("junkemail", "Junk")] if include_spam else [])
    candidates: list[tuple[str, str, str]] = []           # (receivedDateTime, id, folder)
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
        for well_known, label in folders:
            # Graph requires an $orderby property to appear first in $filter (InefficientFilter).
            url: str | None = f"{GRAPH}/mailFolders/{well_known}/messages"
            params: dict | None = {
                "$filter": f"receivedDateTime ge {since}",
                "$orderby": "receivedDateTime asc",
                "$select": "id,from,sender,replyTo,receivedDateTime",
                "$top": "100",
            }
            listed = 0
            while url and listed < _MAX_LISTED:
                resp = await client.get(url, params=params)
                if resp.status_code == 404 and well_known == "junkemail":
                    break                          # some mailboxes have no Junk folder
                _raise_for(resp, "Microsoft")
                body = resp.json()
                for m in body.get("value", []):
                    listed += 1
                    if f"graph:{m['id']}" in skip:
                        continue
                    if any(is_sender(a) for a in _graph_addresses(m)):
                        candidates.append((m.get("receivedDateTime", ""), m["id"], label))
                url, params = body.get("@odata.nextLink"), None     # nextLink carries its own query

        candidates.sort()
        out = CloudRead(more_waiting=len(candidates) > limit)
        for received, mid, label in candidates[:limit]:
            resp = await client.get(f"{GRAPH}/messages/{mid}/$value")
            if resp.status_code == 404:
                continue
            _raise_for(resp, "Microsoft")
            raw = resp.content
            too_large = len(raw) > max_bytes
            when = None
            if received:
                try:
                    when = _utc(datetime.fromisoformat(received.replace("Z", "+00:00")))
                except ValueError:
                    when = None
            out.messages.append(CloudFetched(
                provider_id=f"graph:{mid}", folder=label, internaldate=when, size=len(raw),
                raw=_headers_only(raw) if too_large else raw, too_large=too_large, first_sync=first_sync,
            ))
        return out
