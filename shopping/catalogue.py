import base64
from copy import deepcopy
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests

from .core import GateError, ROOT, atomic_json, fingerprint, utc_now
from .coupang import coupang_url
from .state import validate_catalogue


class Repo:
    def __init__(self, ledger):
        self.ledger = ledger
        self.base = f"https://api.github.com/repos/{ledger.repo}"

    def call(self, method, path, **kwargs):
        response = requests.request(method, self.base + path, headers={
            "Authorization": f"Bearer {self.ledger.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}, timeout=(15, 60), **kwargs)
        if response.status_code >= 400:
            raise GateError(f"Catalog GitHub operation failed (HTTP {response.status_code}); no success fallback")
        return response.json()

    def products(self, ref=None):
        data = self.call("GET", "/contents/products.json", params={"ref": ref or self.ledger.branch})
        return validate_catalogue(json.loads(base64.b64decode(data["content"])))


def read_products(ledger):
    return Repo(ledger).products() if ledger.remote else validate_catalogue(json.loads((ROOT / "products.json").read_text(encoding="utf-8")))


def make_entry(episode, meta, base_url):
    if episode.get("qa_passed") is not True or len(meta.get("scenes", [])) != 3:
        raise GateError("Only a complete verified video can enter the catalog")
    base_url = base_url.rstrip("/") + "/"
    if urlparse(base_url).scheme != "https":
        raise GateError("Public HTTPS catalog URL is required")
    number = episode["catalogue_id"]
    link = episode["product"]["affiliate_link"]
    if not coupang_url(link) or urlparse(link).hostname != "link.coupang.com":
        raise GateError("Catalog requires a real affiliate product link")
    scenes = []
    for index, scene in enumerate(meta["scenes"], 1):
        scenes.append({"image": urljoin(base_url, f"assets/{number}/scene_{index:02d}.jpg"),
                       "badge": scene["badge"], "hook": scene["hook"], "sub": scene["sub"], "tts": scene["narration"]})
    return {"id": number, "title": episode["product"]["title"], "link": link,
            "image": scenes[0]["image"], "verified": True, "scenes": scenes,
            "coupang_product_id": episode["product"]["product_id"], "verified_at": utc_now()}


def merge_products(products, entry):
    result = deepcopy(validate_catalogue(products))
    # Retain all old IDs/data, but remove the known wrong images' approval.
    for row in result:
        urls = [row.get("image", "")] + [s.get("image", "") for s in row.get("scenes", [])]
        if any("1584622650111" in u or "1556911220" in u for u in urls):
            row["verified"] = False
            row["verification_note"] = "Legacy unrelated stock image; historical record retained"
    current = next((p for p in result if p["id"] == entry["id"]), None)
    if current:
        if str(current.get("coupang_product_id")) != entry["coupang_product_id"] or current.get("link") != entry["link"]:
            raise GateError("Catalog ID is already assigned to different data")
        return result
    if any(str(p.get("coupang_product_id")) == entry["coupang_product_id"] for p in result):
        raise GateError("This product already has another catalog number")
    result.insert(0, entry)
    return result


def register(ledger, episode, directory, base_url):
    if not ledger.remote or ledger.branch != "main":
        raise GateError("Catalog publication is allowed only on main with durable state")
    if episode.get("publication_allowed") is not True:
        raise GateError("Selected review sources are preview-only; use approved review sources or official images")
    meta = episode["meta"]
    entry = make_entry(episode, meta, base_url)
    repo = Repo(ledger)
    ref = repo.call("GET", "/git/ref/heads/main")
    head = ref["object"]["sha"]
    current = repo.products(ref=head)
    merged = merge_products(current, entry)
    if any(p["id"] == entry["id"] for p in current):
        ledger.update(episode, catalogue_entry=entry, catalogue_commit=head)
        return entry
    tree = repo.call("GET", "/git/commits/" + head)["tree"]["sha"]
    elements = [{"path": "products.json", "mode": "100644", "type": "blob",
                 "content": json.dumps(merged, ensure_ascii=False, indent=2) + "\n"}]
    for index in range(1, 4):
        image = directory / f"scene_{index:02d}.jpg"
        expected = episode["poster_hashes"][index - 1]
        if fingerprint(image.read_bytes()) != expected:
            raise GateError("Verified catalog image changed")
        blob = repo.call("POST", "/git/blobs", json={"encoding": "base64", "content": base64.b64encode(image.read_bytes()).decode()})
        elements.append({"path": f"assets/{entry['id']}/scene_{index:02d}.jpg", "mode": "100644", "type": "blob", "sha": blob["sha"]})
    new_tree = repo.call("POST", "/git/trees", json={"base_tree": tree, "tree": elements})
    commit = repo.call("POST", "/git/commits", json={"message": f"Publish verified shopping catalog NO.{entry['id']}",
        "tree": new_tree["sha"], "parents": [head]})
    repo.call("PATCH", "/git/refs/heads/main", json={"sha": commit["sha"], "force": False})
    ledger.update(episode, catalogue_entry=entry, catalogue_commit=commit["sha"])
    return entry


def export_site(ledger):
    if not ledger.remote or ledger.branch != "main":
        raise GateError("Only the main catalog can be deployed")
    fetched = subprocess.run(["git", "fetch", "origin", "main"], capture_output=True)
    if fetched.returncode:
        raise GateError("Cannot fetch the committed catalog for Pages deployment")
    archive = subprocess.run(["git", "archive", "--format=tar", "origin/main", "index.html", "products.json", "assets"], capture_output=True)
    if archive.returncode:
        raise GateError("Cannot export committed catalog assets")
    site = ROOT / "site"
    site.mkdir(exist_ok=True)
    with tarfile.open(fileobj=BytesIO(archive.stdout)) as source:
        for member in source.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not member.isfile():
                continue
            target = site.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as input_file:
                target.write_bytes(input_file.read())
    (site / ".nojekyll").touch()
    return site


def verify_live(episode, base_url):
    entry = episode.get("catalogue_entry")
    if not entry:
        raise GateError("Catalog entry has not been committed")
    response = requests.get(base_url.rstrip("/") + "/products.json", params={"verify": fingerprint(entry)[:12]}, timeout=(15, 45))
    if response.status_code != 200:
        raise GateError("Public catalog deployment is not available; YouTube upload is held")
    rows = validate_catalogue(response.json())
    actual = next((p for p in rows if p["id"] == entry["id"]), None)
    if not actual or any(actual.get(k) != entry[k] for k in ("link", "title", "image", "verified", "scenes", "coupang_product_id")):
        raise GateError("Public catalog does not contain the exact verified product/link/number")
    for index, scene in enumerate(entry["scenes"]):
        image = requests.get(scene["image"], timeout=(15, 30))
        if image.status_code != 200 or fingerprint(image.content) != episode["poster_hashes"][index]:
            raise GateError("Public catalog image is missing or differs from verified media")
    return True
