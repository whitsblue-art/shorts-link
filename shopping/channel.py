import re
from urllib.parse import urlparse, unquote

from .core import GateError


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
