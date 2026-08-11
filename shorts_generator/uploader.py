"""YouTube upload via OAuth (optional — needs google-api-python-client).

Setup: place a desktop-app client_secrets.json from Google Cloud Console in the
project root (or set GOOGLE_CLIENT_SECRETS). First upload opens the browser for
authorization; the token is cached in output/.youtube_token.json and refreshed
automatically afterwards.
"""
import os
from pathlib import Path
from typing import Dict, List, Optional

_OUT_ROOT = Path(os.getenv("LOCAL_OUTPUT_DIR") or "output")
_CLIENT_SECRETS = Path(os.getenv("GOOGLE_CLIENT_SECRETS", "client_secrets.json"))
_TOKEN_PATH = _OUT_ROOT / ".youtube_token.json"
_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _deps() -> None:
    try:
        import google_auth_oauthlib  # noqa: F401
        import googleapiclient  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "YouTube upload needs extra deps. Install with:\n"
            "    pip install google-api-python-client google-auth-oauthlib"
        ) from e


def _credentials():
    _deps()
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not _CLIENT_SECRETS.is_file():
        raise RuntimeError(
            "client_secrets.json not found in the project root.\n\n"
            "1. Go to https://console.cloud.google.com/apis/credentials\n"
            "2. Create OAuth client ID → Desktop app\n"
            "3. Download the JSON and save it as client_secrets.json\n"
            "   (gitignored — never commit it)"
        )
    if _TOKEN_PATH.is_file():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), _SCOPES)
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
            _save_token(creds)
            return creds
    flow = InstalledAppFlow.from_client_secrets_file(str(_CLIENT_SECRETS), _SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    _save_token(creds)
    return creds


def _save_token(creds) -> None:
    _OUT_ROOT.mkdir(parents=True, exist_ok=True)
    _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")


def upload_video(
    path: str,
    title: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    privacy_status: str = "public",
) -> Dict:
    """Upload a local video to YouTube. Returns {video_id, url}."""
    _deps()
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    if not os.path.isfile(path):
        raise RuntimeError(f"Video not found: {path}")
    creds = _credentials()
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:500],
            "categoryId": "22",  # People & Blogs
        },
        "status": {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(path, resumable=True, chunksize=8 * 1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and status.resumable_progress:
            print(f"[upload] {int(status.resumable_progress)} bytes", flush=True)
    video_id = response.get("id", "")
    return {"video_id": video_id, "url": f"https://youtu.be/{video_id}"}
