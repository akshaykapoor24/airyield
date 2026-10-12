"""Where received mail lives: the raw .eml and each attachment, through services/file_store.

    mail/{tenant_id}/{connection_id}/{yyyy}/{mm}/{sha256}.eml     the message as received
    mail/{tenant_id}/att/{sha[:2]}/{sha256}                        attachments, content-addressed

The `mail/` prefix makes usage metering attribute it to source "mail" on its own. The bucket
is GCS_MAIL_BUCKET_NAME; without one, file_store's local fallback is MAIL_LOCAL_DIR — never
UPLOAD_DIR, which main.py serves publicly. Attachments are content-addressed per workspace,
so a statement attached to five replies is stored once (and never shared across workspaces).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.services import file_store


def bucket() -> str:
    return settings.GCS_MAIL_BUCKET_NAME


def local_root() -> Path:
    root = Path(settings.MAIL_LOCAL_DIR)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / root      # …/backend/<MAIL_LOCAL_DIR>
    return root


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def store_raw(tenant_id: int, connection_id: int, raw: bytes, when: datetime) -> tuple[str, str]:
    digest = sha256(raw)
    name = f"mail/{tenant_id}/{connection_id}/{when:%Y}/{when:%m}/{digest}.eml"
    locator, _ = await file_store.store(raw, name, "message/rfc822", bucket(), local_root=local_root())
    return locator, digest


async def store_attachment(tenant_id: int, data: bytes, content_type: str) -> tuple[str, str]:
    digest = sha256(data)
    name = f"mail/{tenant_id}/att/{digest[:2]}/{digest}"
    locator, _ = await file_store.store(data, name, content_type or "application/octet-stream",
                                        bucket(), local_root=local_root())
    return locator, digest


async def load(locator: str) -> bytes:
    return await file_store.load(locator, bucket(), local_root=local_root())
