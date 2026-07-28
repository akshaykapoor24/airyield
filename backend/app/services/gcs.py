import asyncio
import logging
from datetime import timedelta

from google.cloud import storage
from google.oauth2 import service_account

from app.config import settings

logger = logging.getLogger(__name__)


def _get_client() -> storage.Client:
    email       = settings.GCS_SERVICE_ACCOUNT_EMAIL
    private_key = settings.GCS_SERVICE_ACCOUNT_PRIVATE_KEY.replace("\\n", "\n")
    project_id  = settings.GCS_PROJECT_ID

    logger.info("[GCS] Auth | email=%s | project=%s", email, project_id)

    creds = service_account.Credentials.from_service_account_info(
        {
            "type": "service_account",
            "project_id": project_id,
            "private_key_id": "",
            "private_key": private_key,
            "client_email": email,
            "client_id": "",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
    )
    return storage.Client(credentials=creds, project=project_id)


def _bucket(bucket_name: str) -> storage.Bucket:
    if not bucket_name:
        raise ValueError("[GCS] bucket_name is empty — check GCS_DEALS_BUCKET_NAME / GCS_TICKETS_BUCKET_NAME in .env")
    return _get_client().bucket(bucket_name)


async def upload_bytes(content: bytes, blob_name: str, content_type: str, bucket_name: str) -> str:
    """Upload bytes to GCS bucket. Returns blob_name (the stored path)."""
    logger.info("[GCS] Uploading | bucket=%s | blob=%s | size=%d bytes", bucket_name, blob_name, len(content))

    loop = asyncio.get_event_loop()

    def _do() -> str:
        try:
            blob = _bucket(bucket_name).blob(blob_name)
            blob.upload_from_string(content, content_type=content_type)
            logger.info("[GCS] Upload SUCCESS | bucket=%s | blob=%s", bucket_name, blob_name)
            return blob_name
        except Exception as e:
            logger.error("[GCS] Upload FAILED | bucket=%s | blob=%s | error: %s", bucket_name, blob_name, e, exc_info=True)
            raise

    return await loop.run_in_executor(None, _do)


async def download_bytes(blob_name: str, bucket_name: str) -> bytes:
    """Download a blob's bytes from GCS. Used by the BSP worker to fetch the
    uploaded PDF for parsing."""
    logger.info("[GCS] Downloading | bucket=%s | blob=%s", bucket_name, blob_name)

    loop = asyncio.get_event_loop()

    def _do() -> bytes:
        try:
            blob = _bucket(bucket_name).blob(blob_name)
            content = blob.download_as_bytes()
            logger.info("[GCS] Download SUCCESS | bucket=%s | blob=%s | size=%d bytes", bucket_name, blob_name, len(content))
            return content
        except Exception as e:
            logger.error("[GCS] Download FAILED | bucket=%s | blob=%s | error: %s", bucket_name, blob_name, e, exc_info=True)
            raise

    return await loop.run_in_executor(None, _do)


async def blob_exists(blob_name: str, bucket_name: str) -> bool:
    """True if the blob exists (used to reuse a cached xlsx preview conversion)."""
    loop = asyncio.get_event_loop()

    def _do() -> bool:
        try:
            return _bucket(bucket_name).blob(blob_name).exists()
        except Exception:  # noqa: BLE001
            return False

    return await loop.run_in_executor(None, _do)


async def delete_blob(blob_name: str, bucket_name: str) -> None:
    """Best-effort delete of a blob (used when a BSP statement is deleted)."""
    loop = asyncio.get_event_loop()

    def _do() -> None:
        try:
            _bucket(bucket_name).blob(blob_name).delete()
            logger.info("[GCS] Delete OK | bucket=%s | blob=%s", bucket_name, blob_name)
        except Exception as e:
            logger.warning("[GCS] Delete FAILED (ignored) | bucket=%s | blob=%s | error: %s", bucket_name, blob_name, e)

    await loop.run_in_executor(None, _do)


async def generate_signed_url(
    blob_name: str,
    bucket_name: str,
    expiry_minutes: int = 60,
    inline: bool = False,
    content_type: str | None = None,
) -> str:
    """Return a V4 signed GET URL valid for expiry_minutes.

    inline=True  → response-content-disposition=inline  (browser displays the file)
    inline=False → response-content-disposition=attachment (browser downloads it)
    content_type → optional response-content-type override (e.g. force a .csv to be
                   served as text/plain so the browser shows it inline instead of
                   downloading it as text/csv).
    """
    logger.info("[GCS] Generating signed URL | bucket=%s | blob=%s | inline=%s", bucket_name, blob_name, inline)

    loop = asyncio.get_event_loop()

    def _do() -> str:
        try:
            blob = _bucket(bucket_name).blob(blob_name)
            filename = blob_name.split("/")[-1]
            kwargs: dict = {
                "version": "v4",
                "expiration": timedelta(minutes=expiry_minutes),
                "method": "GET",
                "response_disposition": f"{'inline' if inline else 'attachment'}; filename=\"{filename}\"",
            }
            if content_type:
                kwargs["response_type"] = content_type
            url = blob.generate_signed_url(**kwargs)
            logger.info("[GCS] Signed URL OK | bucket=%s | blob=%s", bucket_name, blob_name)
            return url
        except Exception as e:
            logger.error("[GCS] Signed URL FAILED | bucket=%s | blob=%s | error: %s", bucket_name, blob_name, e, exc_info=True)
            raise

    return await loop.run_in_executor(None, _do)
