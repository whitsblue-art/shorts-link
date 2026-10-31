import re
import json
import requests
from urllib.parse import urlparse, unquote

from .core import GateError


def public_channel(target):
    parsed = urlparse(target)
    if parsed.scheme != "https" or parsed.hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        raise GateError("Public channel lookup requires a YouTube HTTPS URL")
    try:
        response = requests.get(target, headers={"User-Agent": "Mozilla/5.0"}, timeout=(15, 45))
        if response.status_code != 200:
            raise GateError(f"Public YouTube channel lookup returned HTTP {response.status_code}")
        match = re.search(r'"channelMetadataRenderer"\s*:\s*', response.text)
        if not match:
            raise GateError("Public channel metadata unavailable; OAuth lookup is still required")
        data, _ = json.JSONDecoder().raw_decode(response.text[match.end():])
        channel_id = data.get("externalId", "")
        if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id) or not data.get("title"):
            raise GateError("Public YouTube channel identity is incomplete")
        return {"channel_id": channel_id, "title": data["title"], "url": data.get("channelUrl", target)}
    except requests.RequestException:
        raise GateError("Public YouTube channel lookup failed; no identity assumed") from None


def resolve_channel(youtube, target):
    target = target.strip()
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", target):
        return target
    handle = target if target.startswith("@") else None
    if not handle:
        parsed = urlparse(target)
        if parsed.scheme != "https" or parsed.hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            raise GateError("Set SHOPPING_CHANNEL_URL to the intended shopping channel URL or ID")
        parts = unquote(parsed.path).strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "channel" and re.fullmatch(r"UC[A-Za-z0-9_-]{22}", parts[1]):
            return parts[1]
        if parts[0].startswith("@"):
            handle = parts[0]
    if not handle or not re.fullmatch(r"@[\w.\-가-힣]+", handle):
        raise GateError("Use a /channel/UC... or /@handle shopping channel URL")
    items = youtube.channels().list(part="id", forHandle=handle).execute().get("items", [])
    if len(items) != 1:
        raise GateError("The intended shopping channel could not be resolved")
    return items[0]["id"]
