"""
cache.py — GCS-backed cache for dashboard data.

Stores a single JSON blob `latest.json` in the configured GCS bucket.
The blob is written atomically (upload replaces the previous version).

Client is initialized at module level and reused across requests.
ADC (Application Default Credentials) resolves automatically on Cloud Run
via the attached service account — no credential files needed.
"""
import json
import logging

from google.cloud import storage

import config

logger = logging.getLogger(__name__)

_CACHE_KEY = "latest.json"

# Module-level client — initialized once, reused across requests
_gcs_client: storage.Client | None = None


def _get_client() -> storage.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client()
    return _gcs_client


def read_cache() -> dict | None:
    """
    Read the cached dashboard data from GCS.

    Returns the parsed JSON dict, or None if:
      - The blob does not exist (first deploy, before any refresh)
      - A GCS error occurs (logged; caller decides how to respond)
    """
    try:
        client = _get_client()
        bucket = client.bucket(config.CACHE_BUCKET)
        blob = bucket.blob(_CACHE_KEY)
        if not blob.exists():
            logger.warning("Cache blob %s not found in bucket %s", _CACHE_KEY, config.CACHE_BUCKET)
            return None
        content = blob.download_as_text(encoding="utf-8")
        return json.loads(content)
    except Exception as exc:
        logger.error("Failed to read cache from GCS: %s", exc)
        return None


def write_cache(data: dict) -> None:
    """
    Write dashboard data to GCS cache.

    The upload is atomic: GCS replaces the previous blob version.
    Raises on failure — caller (api_refresh) handles and returns 500.

    Args:
        data: Dict with keys ventas, mix, cerv, gin, ferid, last_updated
    """
    client = _get_client()
    bucket = client.bucket(config.CACHE_BUCKET)
    blob = bucket.blob(_CACHE_KEY)
    blob.upload_from_string(
        json.dumps(data, ensure_ascii=False),
        content_type="application/json",
    )
    logger.info(
        "Cache written to gs://%s/%s (%d bytes)",
        config.CACHE_BUCKET,
        _CACHE_KEY,
        len(json.dumps(data)),
    )
