import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone

import requests

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


class GateError(RuntimeError):
    """A required quality or publication gate did not pass."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def normalize(text):
    return re.sub(r"[^가-힣a-z0-9]", "", str(text).lower())


def fingerprint(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(value).hexdigest()


def run(command, timeout=300, cwd=None):
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, cwd=cwd)
    if result.returncode:
        raise GateError(f"{command[0]} failed: {result.stderr[-1800:]}")
    return result


def require_pass(result, checks):
    if not isinstance(result, dict) or result.get("verdict") != "PASS":
        raise GateError(f"Reviewer did not approve: {result}")
    if any(result.get("checks", {}).get(check) != "PASS" for check in checks):
        raise GateError(f"Reviewer omitted or rejected required checks: {result}")
    return result


class Journal:
    """Write-through state. GitHub Contents SHA is a compare-and-swap lease.

    Every upload intent must be persisted before sending video bytes. An ambiguous
    response is reconciled by episode marker; it is never blindly re-uploaded.
    """

    def __init__(self, remote=False):
        self.remote = remote
        self.path = ROOT / ".local-state" / "pipeline_state.json"
        self.sha = None
        self.token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN", "")
        self.repo = os.getenv("GITHUB_REPOSITORY", "")
        self.branch = os.getenv("GITHUB_REF_NAME", "main")
        if remote and (not self.token or not re.fullmatch(r"[\w.-]+/[\w.-]+", self.repo)):
            raise GateError("Publishing requires GITHUB_TOKEN and GITHUB_REPOSITORY for durable state")
        self.url = f"https://api.github.com/repos/{self.repo}/contents/pipeline_state.json"
        if remote:
            response = self._request("GET", params={"ref": self.branch})
            if response.status_code == 404:
                self.data = self.empty()
            else:
                self._ok(response)
                obj = response.json()
                self.sha = obj["sha"]
                self.data = json.loads(base64.b64decode(obj["content"]))
        elif self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = self.empty()
        if self.data.get("version") != 1 or not isinstance(self.data.get("episodes"), dict):
            raise GateError("Invalid journal; refusing to reset publication history")

    @staticmethod
    def empty():
        return {"version": 1, "channel_id": None, "plans": {}, "episodes": {}}

    def _request(self, method, **kwargs):
        # Do not retry PUT automatically: its successful response may have been lost.
        return requests.request(method, self.url, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}, timeout=(15, 45), **kwargs)

    @staticmethod
    def _ok(response):
        if response.status_code >= 400:
            raise GateError(f"Durable GitHub state write/read failed (HTTP {response.status_code}); stop")

    def save(self):
        self.data["updated_at"] = utc_now()
        if self.remote:
            body = {"message": "chore: checkpoint video pipeline", "branch": self.branch,
                    "content": base64.b64encode((json.dumps(self.data, ensure_ascii=False, indent=2) + "\n").encode()).decode()}
            if self.sha:
                body["sha"] = self.sha
            response = self._request("PUT", json=body)
            self._ok(response)
            self.sha = response.json()["content"]["sha"]
        atomic_json(self.path, self.data)

    def update(self, episode, **fields):
        episode.update(fields, updated_at=utc_now())
        if episode.get("status") == "published" and "meta" in episode:
            episode["title"] = episode["meta"]["title"]
            episode.pop("meta")  # Keep the durable journal compact; full evidence lives in artifacts.
        self.save()

