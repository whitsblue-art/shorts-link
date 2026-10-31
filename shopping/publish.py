"""Private upload, recovery by unique metadata tag, verification, then release."""
import json
import os
from pathlib import Path
import time

from .core import GateError, atomic_json, fingerprint, utc_now
from .channel import resolve_channel


def connect_youtube():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    raw = os.getenv("SHOPPING_YOUTUBE_TOKEN_JSON", "").strip()
    if not raw:
        raise GateError("SHOPPING_YOUTUBE_TOKEN_JSON missing; connect the shopping channel separately")
    try:
        token_info = json.loads(raw)
        scopes = token_info.get("scopes", [])
        if scopes:
            if isinstance(scopes, str):
                scopes = scopes.split()
            if not any(s in scopes for s in ("https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.force-ssl")):
                raise GateError("Existing YouTube token is upload-only. Reauthorize once using authorize_youtube.py "
                                "and update SHOPPING_YOUTUBE_TOKEN_JSON to enable private-to-public verification")
        creds = Credentials.from_authorized_user_info(token_info)
        if not creds.valid:
            if not creds.refresh_token:
                raise GateError("YouTube refresh token missing")
            creds.refresh(Request())
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    except GateError:
        raise
    except Exception:
        raise GateError("YouTube authentication failed; token details are not logged") from None


class Publisher:
    def __init__(self, journal, youtube=None, sleep=time.sleep, catalogue_gate=None):
        self.journal = journal
        self.youtube = youtube or connect_youtube()
        self.sleep = sleep
        self.catalogue_gate = catalogue_gate
        try:
            channels = self.youtube.channels().list(part="id,contentDetails", mine=True).execute().get("items", [])
        except Exception:
            raise GateError("Cannot read the authorized YouTube channel. Existing OAuth token may be upload-only; "
                            "see README OAuth setup for read/status-update scopes") from None
        if len(channels) != 1:
            raise GateError("Cannot uniquely identify the authorized YouTube channel; check OAuth read scope")
        self.channel_id = channels[0]["id"]
        self.uploads = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        from .core import ROOT
        settings = json.loads((ROOT / "shopping_config.json").read_text(encoding="utf-8"))
        target = os.getenv("SHOPPING_CHANNEL_URL") or settings.get("shopping_channel_url", "")
        expected = resolve_channel(self.youtube, target)
        if self.channel_id != expected or (journal.data.get("channel_id") and journal.data["channel_id"] != expected):
            raise GateError("YouTube token belongs to a different channel")
        if not journal.data.get("channel_id"):
            journal.data["channel_id"] = self.channel_id
            journal.save()

    @staticmethod
    def marker(episode):
        return "shopping-episode-" + episode["id"]

    def details(self, video_id):
        items = self.youtube.videos().list(part="snippet,status,processingDetails", id=video_id).execute().get("items", [])
        if len(items) != 1:
            raise GateError("Saved YouTube video is not readable; refusing to create another upload")
        return items[0]

    def verify_identity(self, episode, video):
        if (video["snippet"]["channelId"] != self.channel_id or
                self.marker(episode) not in video["snippet"].get("tags", [])):
            raise GateError("Saved/recovered video does not match this episode and channel")

    def recover(self, episode):
        matches, page = [], None
        for _ in range(20):
            args = {"part": "contentDetails", "playlistId": self.uploads, "maxResults": 50}
            if page:
                args["pageToken"] = page
            result = self.youtube.playlistItems().list(**args).execute()
            ids = [item["contentDetails"]["videoId"] for item in result.get("items", [])]
            if ids:
                videos = self.youtube.videos().list(part="snippet,status,processingDetails", id=",".join(ids)).execute()
                for video in videos.get("items", []):
                    if self.marker(episode) in video["snippet"].get("tags", []):
                        self.verify_identity(episode, video)
                        matches.append(video["id"])
            page = result.get("nextPageToken")
            if not page:
                break
        if len(matches) > 1:
            raise GateError("Multiple uploads share this episode ID; human reconciliation required")
        return matches[0] if matches else None

    def resolve(self, episode, video_id):
        video = self.details(video_id)
        self.verify_identity(episode, video)
        self.journal.update(episode, video_id=video_id, status="uploaded")

    def upload(self, episode, path, meta):
        if episode.get("publication_allowed") is not True or not callable(self.catalogue_gate):
            raise GateError("Product media and live catalog must be approved before upload")
        self.catalogue_gate(episode)
        if episode.get("video_id"):
            video = self.details(episode["video_id"])
            self.verify_identity(episode, video)
            return episode["video_id"]
        uncertain = episode["status"] in ("uploading", "upload_unknown")
        existing = self.recover(episode)
        if existing:
            self.journal.update(episode, video_id=existing, status="uploaded")
            return existing
        if uncertain:
            raise GateError("Previous upload outcome is uncertain. No second upload will be attempted. "
                            "Check Studio, rerun later, or use resolve_video_id for the matching video")
        if episode["status"] != "verified" or episode.get("qa_passed") is not True:
            raise GateError("Publication requires all QA gates to pass")
        if not path or not Path(path).is_file() or fingerprint(Path(path).read_bytes()) != episode.get("video_sha256"):
            raise GateError("Video changed after verification or is missing")
        body = {"snippet": {"title": meta["title"], "description": meta["upload_description"],
                "tags": ["쿠팡파트너스", "생활용품", "상품소개", self.marker(episode), "Shorts"],
                "categoryId": "26", "defaultLanguage": "ko", "defaultAudioLanguage": "ko"},
                "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}}
        # The durable intent must succeed BEFORE the API can receive any video bytes.
        self.journal.update(episode, status="uploading", upload_started_at=utc_now())
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(str(path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
        try:
            request = self.youtube.videos().insert(part="snippet,status", body=body,
                media_body=media)
            result = None
            while result is None:
                _, result = request.next_chunk(num_retries=0)
            video_id = result["id"]
        except Exception:
            self.journal.update(episode, status="upload_unknown")
            raise GateError("Upload response was ambiguous; publication paused to prevent duplicates") from None
        finally:
            media.stream().close()
        # If this state write fails, 'uploading' is already durable and next run recovers the tag.
        self.journal.update(episode, status="uploaded", video_id=video_id)
        return video_id

    def wait_for_processing(self, episode, polls=60):
        for index in range(polls):
            video = self.details(episode["video_id"])
            self.verify_identity(episode, video)
            status = video.get("status", {})
            processing = video.get("processingDetails", {}).get("processingStatus")
            if status.get("uploadStatus") in ("failed", "rejected", "deleted") or processing in ("failed", "terminated"):
                raise GateError("YouTube rejected or failed processing; video remains unreleased")
            if status.get("uploadStatus") == "processed" and processing in (None, "succeeded"):
                return video
            if index + 1 < polls:
                self.sleep(10)
        raise GateError("YouTube processing timed out; resume this video ID later")

    def set_thumbnail(self, episode, path):
        if episode.get("thumbnail_status") == "set":
            return
        if not path or not Path(path).is_file():
            raise GateError("Reviewed thumbnail missing; restore episode artifacts before resuming")
        if fingerprint(Path(path).read_bytes()) != episode.get("thumbnail_sha256"):
            raise GateError("Thumbnail changed after verification")
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(str(path), mimetype="image/jpeg")
        try:
            result = self.youtube.thumbnails().set(videoId=episode["video_id"],
                media_body=media).execute()
            if not result.get("items"):
                raise GateError("Thumbnail API returned no registered image")
            self.journal.update(episode, thumbnail_status="set")
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            try:
                reasons = {item.get("reason") for item in json.loads(getattr(exc, "content", b"{}")).get("error", {}).get("errors", [])}
            except (ValueError, TypeError):
                reasons = set()
            # Only a known unsupported/permission response can be optional for Shorts.
            # Network/server/auth errors remain failures and are retried on a later run.
            if (episode["format"] == "shorts" and os.getenv("SHORTS_THUMBNAIL_MODE", "try") == "try"
                    and status in (400, 403) and reasons.intersection({"forbidden", "unsupportedVideoType", "unsupportedForShorts"})):
                self.journal.update(episode, thumbnail_status="manual_required", thumbnail_http_status=status)
                print("Shorts thumbnail API unavailable: reviewed image is in artifacts; Studio registration required", flush=True)
            else:
                raise GateError("Thumbnail registration failed; video remains private") from None
        finally:
            media.stream().close()

    def publish(self, episode, path=None, thumbnail=None):
        if episode["status"] == "published":
            return episode["video_id"]
        if episode.get("qa_passed") is not True:
            raise GateError("Quality gate is not approved")
        meta = episode["meta"]
        self.upload(episode, path, meta)
        current = self.wait_for_processing(episode)
        self.set_thumbnail(episode, thumbnail)
        # Repeating a status update is safe; repeating a video insert is not.
        if current["status"].get("privacyStatus") != "public":
            status = {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
            if "containsSyntheticMedia" in current["status"]:
                status["containsSyntheticMedia"] = current["status"]["containsSyntheticMedia"]
            self.youtube.videos().update(part="status", body={"id": episode["video_id"], "status": status}).execute()
        actual = self.details(episode["video_id"])
        self.verify_identity(episode, actual)
        if actual["status"].get("privacyStatus") != "public" or actual["status"].get("uploadStatus") != "processed":
            raise GateError("YouTube public/processed state was not confirmed")
        self.journal.update(episode, status="published", published_at=utc_now())
        return episode["video_id"]
