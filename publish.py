"""publish.py — Upload the finished video to YouTube."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_TOKEN_FILE = "youtube_token.json"
_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def upload_to_youtube(
    video_path: Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "22",   # 22 = People & Blogs
    privacy: str = "public",
) -> str:
    """Upload *video_path* to YouTube and return the video URL."""
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.http import MediaFileUpload  # type: ignore
    from googleapiclient.errors import HttpError  # type: ignore
    import google.auth.transport.requests  # type: ignore
    import json

    creds = _load_or_create_creds(json, Credentials, InstalledAppFlow,
                                   google.auth.transport.requests)

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {"privacyStatus": privacy},
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
    )

    logger.info("Uploading %s to YouTube...", video_path.name)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Upload progress: %d%%", int(status.progress() * 100))

    video_id: str = response["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    logger.info("Uploaded! %s", url)
    return url


def _load_or_create_creds(json, Credentials, InstalledAppFlow, google_auth_requests):
    import pickle

    if os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(google_auth_requests.Request())
            _save_token(pickle, creds)
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(
        config.YOUTUBE_CLIENT_SECRETS, _SCOPES
    )
    creds = flow.run_local_server(port=0)
    _save_token(pickle, creds)
    return creds


def _save_token(pickle, creds) -> None:
    with open(_TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)
    logger.debug("YouTube token cached to %s", _TOKEN_FILE)
