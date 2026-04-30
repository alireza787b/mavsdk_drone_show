"""Shared helpers for drone/SITL requests to an auth-protected GCS API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from mds_logging import get_logger

logger = get_logger("gcs_auth_client")

_TOKEN_READ_ERROR_LOGGED = False


def read_gcs_api_token() -> str | None:
    """Return the configured GCS API bearer token, if one is available.

    MDS supports file-based bearer tokens only. Raw secret environment
    variables are intentionally not accepted because they leak too easily
    through process listings, shell history, and diagnostics.
    """
    global _TOKEN_READ_ERROR_LOGGED

    token_file = os.environ.get("MDS_GCS_API_TOKEN_FILE", "").strip()
    if not token_file:
        return None

    try:
        token = Path(token_file).expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        if not _TOKEN_READ_ERROR_LOGGED:
            _TOKEN_READ_ERROR_LOGGED = True
            logger.warning("GCS API token file is configured but unreadable: %s", exc)
        return None

    return token or None


def gcs_auth_headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return Authorization headers for GCS requests without logging secrets."""
    headers = dict(extra or {})
    token = read_gcs_api_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
