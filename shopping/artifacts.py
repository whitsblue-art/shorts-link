"""Restore the exact reviewed files from an earlier run, never regenerate a published upload."""
from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import shutil
import zipfile

import requests

from .core import GateError


def restore(journal, episode, directory):
    run_id = episode.get("artifact_run_id")
    if not journal.remote or not run_id:
        return False
    headers = {"Authorization": f"Bearer {journal.token}", "Accept": "application/vnd.github+json"}
    response = requests.get(f"https://api.github.com/repos/{journal.repo}/actions/runs/{run_id}/artifacts",
                            headers=headers, timeout=(15, 45))
    if response.status_code != 200:
        return False
    name = f"pipeline-{run_id}-{episode.get('artifact_run_attempt', '1')}"
    artifact = next((a for a in response.json().get("artifacts", []) if a["name"] == name and not a["expired"]), None)
    if not artifact:
        artifact = next((a for a in response.json().get("artifacts", [])
                         if a["name"] == "reviewed-short-preview" and not a["expired"]), None)
    if not artifact:
        return False
    response = requests.get(f"https://api.github.com/repos/{journal.repo}/actions/artifacts/{artifact['id']}/zip",
                            headers=headers, timeout=(15, 180))
    if response.status_code != 200:
        return False
    extracted = False
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        selected = [m for m in archive.infolist() if PurePosixPath(m.filename).parts[:1] == (episode["id"],)]
        if sum(m.file_size for m in selected) > 1_500_000_000:
            raise GateError("Artifact is unexpectedly large")
        for member in selected:
            path = PurePosixPath(member.filename)
            if ".." in path.parts or path.is_absolute() or "\\" in member.filename or ":" in member.filename:
                raise GateError("Unsafe artifact path")
            target = directory.joinpath(*path.parts[1:])
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                extracted = True
    return extracted
