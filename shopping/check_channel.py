"""Read-only OAuth/target verification before spending generation quota."""
import json
import os
from .core import GateError, ROOT
from .channel import resolve_channel
from .publish import connect_youtube


def main():
    youtube = connect_youtube()
    config = json.loads((ROOT / "shopping_config.json").read_text(encoding="utf-8"))
    target = resolve_channel(youtube, os.getenv("SHOPPING_CHANNEL_URL") or config.get("shopping_channel_url", ""))
    if config.get("shopping_channel_id") and target != config["shopping_channel_id"]:
        raise GateError("Configured destination differs from the verified shopping channel ID")
    channels = youtube.channels().list(part="id", mine=True).execute().get("items", [])
    if len(channels) != 1 or channels[0]["id"] != target:
        raise GateError("Shopping OAuth channel does not match the configured destination")
    print("Shopping OAuth and intended destination channel match")


if __name__ == "__main__":
    main()
