"""Run locally once if the existing token lacks read/status-update permissions.

This helper is never called by Actions. It writes an ignored file instead of
printing access/refresh tokens to a console or Actions log.
"""
import argparse
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("client_secret", type=Path, help="Google Cloud desktop OAuth client JSON")
    parser.add_argument("--output", type=Path, default=Path("shopping_youtube_token.json"))
    args = parser.parse_args()
    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secret), scopes=[
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    ])
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    print(f"Saved credentials to {args.output}. Set this file's contents as the SHOPPING_YOUTUBE_TOKEN_JSON secret; do not commit it.")


if __name__ == "__main__":
    main()
