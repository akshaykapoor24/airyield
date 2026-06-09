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


async def generate_signed_url(blob_name: str, bucket_name: str, expiry_minutes: int = 60, inline: bool = False) -> str:
    """Return a V4 signed GET URL valid for expiry_minutes.
    inline=True adds response-content-disposition=inline so browsers display instead of downloading.
    """
    logger.info("[GCS] Generating signed URL | bucket=%s | blob=%s | inline=%s", bucket_name, blob_name, inline)

    loop = asyncio.get_event_loop()

    def _do() -> str:
        try:
            blob = _bucket(bucket_name).blob(blob_name)
            kwargs: dict = {
                "version": "v4",
                "expiration": timedelta(minutes=expiry_minutes),
                "method": "GET",
            }
            if inline:
                filename = blob_name.split("/")[-1]
                kwargs["response_disposition"] = f"inline; filename=\"{filename}\""
            url = blob.generate_signed_url(**kwargs)
            logger.info("[GCS] Signed URL OK | bucket=%s | blob=%s", bucket_name, blob_name)
            return url
        except Exception as e:
            logger.error("[GCS] Signed URL FAILED | bucket=%s | blob=%s | error: %s", bucket_name, blob_name, e, exc_info=True)
            raise

    return await loop.run_in_executor(None, _do)
