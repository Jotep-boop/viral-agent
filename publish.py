"""publish.py — Upload the finished video to YouTube."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_TOKEN_FILE = config.BASE_DIR / "youtube_token.json"
_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def upload_to_youtube(
    video_path: Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "22",   # 22 = People & Blogs
    privacy: str = "public",
    default_language: str = "en",
    default_audio_language: str = "en",
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
            "defaultLanguage": default_language,
            "defaultAudioLanguage": default_audio_language,
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

    if _TOKEN_FILE.exists():
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


def get_channel_stats() -> dict:
    """Return channel statistics (subscribers, total views, video count)."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    import google.auth.transport.requests
    import json

    creds = _load_or_create_creds(json, Credentials, InstalledAppFlow,
                                   google.auth.transport.requests)
    youtube = build("youtube", "v3", credentials=creds)

    resp = youtube.channels().list(part="snippet,statistics", mine=True).execute()
    if not resp.get("items"):
        return {"error": "No channel found"}

    channel = resp["items"][0]
    stats = channel["statistics"]
    return {
        "channel_title": channel["snippet"]["title"],
        "subscribers": int(stats.get("subscriberCount", 0)),
        "total_views": int(stats.get("viewCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
    }


def get_video_stats(video_id: str) -> dict:
    """Return statistics for a specific video."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    import google.auth.transport.requests
    import json

    creds = _load_or_create_creds(json, Credentials, InstalledAppFlow,
                                   google.auth.transport.requests)
    youtube = build("youtube", "v3", credentials=creds)

    resp = youtube.videos().list(part="snippet,statistics", id=video_id).execute()
    if not resp.get("items"):
        return {"error": f"Video {video_id} not found"}

    video = resp["items"][0]
    stats = video["statistics"]
    return {
        "title": video["snippet"]["title"],
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
        "published_at": video["snippet"]["publishedAt"],
    }


def list_recent_videos(max_results: int = 10) -> list[dict]:
    """Return recent uploads with their stats."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    import google.auth.transport.requests
    import json

    creds = _load_or_create_creds(json, Credentials, InstalledAppFlow,
                                   google.auth.transport.requests)
    youtube = build("youtube", "v3", credentials=creds)

    # Get uploads playlist
    ch_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    if not ch_resp.get("items"):
        return []
    uploads_id = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Get recent videos from uploads playlist
    pl_resp = youtube.playlistItems().list(
        part="snippet", playlistId=uploads_id, maxResults=max_results
    ).execute()

    video_ids = [item["snippet"]["resourceId"]["videoId"]
                 for item in pl_resp.get("items", [])]
    if not video_ids:
        return []

    # Get stats for all videos in one call
    v_resp = youtube.videos().list(
        part="snippet,statistics", id=",".join(video_ids)
    ).execute()

    results = []
    for v in v_resp.get("items", []):
        stats = v["statistics"]
        results.append({
            "video_id": v["id"],
            "title": v["snippet"]["title"],
            "published_at": v["snippet"]["publishedAt"],
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
        })
    return results


def _save_token(pickle, creds) -> None:
    with open(_TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)
    logger.debug("YouTube token cached to %s", _TOKEN_FILE)
