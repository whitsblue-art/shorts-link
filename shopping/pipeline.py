import argparse
import json
import os
from pathlib import Path
import re
import shutil

from .ai import AI
from .artifacts import restore
from .assets import collect, allowed_source
from .catalogue import read_products, register, export_site, verify_live
from .core import GateError, ROOT, atomic_json, fingerprint
from .coupang import Coupang
from . import design, media, script
from .publish import Publisher
from .state import Ledger


def output(**values):
    target = os.getenv("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def verified_files(episode, directory):
    for name, expected in episode.get("asset_hashes", {}).items():
        path = directory / name
        if Path(name).name != name or not path.is_file() or fingerprint(path.read_bytes()) != expected:
            raise GateError("Reviewed episode assets are missing or modified; restore the original artifact")
    if not episode.get("asset_hashes") or not episode.get("qa_passed"):
        raise GateError("No complete reviewed asset receipt")


def prepare_episode(ai, ledger, episode, assets, settings, directory):
    meta_path = directory / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else script.generate(
        ai, episode["product"], episode["catalogue_id"], assets, directory)
    script.validate(meta, episode["catalogue_id"])
    meta["product_title"] = episode["product"]["title"]
    base = settings["catalogue_base_url"].rstrip("/") + "/"
    meta["upload_description"] = (design.DISCLOSURE + "\n\n" + meta["description"] + "\n\n"
        f"상품 정보: 채널 프로필 링크에서 [{episode['catalogue_id']}번] 검색\n"
        + base + "\n가격·옵션·호환 여부는 상품 페이지에서 확인하세요.\n#Shorts #쿠팡파트너스 #생활용품")
    atomic_json(meta_path, meta)
    timings = media.generate_voices(ai, meta, "shorts", directory)
    final, manifest = design.render(meta, directory, timings)
    signal = media.validate_video(final, manifest, media.PROFILES["shorts"])
    design.review(ai, meta, final, manifest, directory)
    thumbnail = design.thumbnail(ai, meta, directory)
    names = ["final_shorts.mp4", "thumbnail.jpg", "meta.json", "assets.json", "reference.jpg"]
    names += [f"scene_{n:02d}.jpg" for n in range(1, 4)]
    hashes = {name: fingerprint((directory / name).read_bytes()) for name in names}
    ledger.update(episode, status="verified", qa_passed=True, meta=meta,
        publication_allowed=all(a.get("publication_allowed") is True for a in assets),
        poster_hashes=[hashes[f"scene_{n:02d}.jpg"] for n in range(1, 4)], asset_hashes=hashes,
        video_sha256=hashes[final.name], thumbnail_sha256=hashes[thumbnail.name], signal=signal,
        artifact_run_id=os.getenv("GITHUB_RUN_ID"), artifact_run_attempt=os.getenv("GITHUB_RUN_ATTEMPT", "1"))
    videos = ROOT / "videos"
    videos.mkdir(exist_ok=True)
    shutil.copyfile(final, videos / f"shorts_no_{episode['catalogue_id']}.mp4")
    media.clean_intermediates(directory)


def prepare(ledger, settings, publish):
    media.preflight()
    run_key = os.getenv("GITHUB_RUN_ID")
    prior_id = ledger.data["plans"].get(run_key) if run_key else None
    prior = ledger.data["episodes"].get(prior_id)
    if prior and prior["status"] == "published":
        return prior  # GitHub's "Re-run jobs" is the same run, not a new publishing slot.
    pending = ledger.pending()
    if pending:
        if run_key:
            ledger.data["plans"][run_key] = pending["id"]
            ledger.save()
        directory = ROOT / "current_episode" / pending["id"]
        directory.mkdir(parents=True, exist_ok=True)
        if not (directory / "assets.json").exists():
            restore(ledger, pending, directory)
        if pending.get("qa_passed"):
            verified_files(pending, directory)
            if publish and pending.get("publication_allowed") is not True:
                assets = json.loads((directory / "assets.json").read_text(encoding="utf-8"))
                registry = json.loads((ROOT / "product_sources.json").read_text(encoding="utf-8"))
                licensed = {m["url"] for row in registry if str(row.get("product_id")) == pending["product"]["product_id"]
                    for m in row.get("media", []) if m.get("publication_allowed") is True}
                allowed = all(a.get("publication_allowed") is True or a["url"] in licensed
                    or allowed_source(a.get("source_url", ""), settings.get("approved_review_url_prefixes", [])) for a in assets)
                if not allowed:
                    raise GateError("Pending preview uses unapproved review media; configure source permission before promotion")
                ledger.update(pending, publication_allowed=True)
            return pending
        assets = json.loads((directory / "assets.json").read_text(encoding="utf-8"))
        prepare_episode(AI(), ledger, pending, assets, settings, directory)
        return pending
    api, ai = Coupang(), AI()
    products = read_products(ledger)
    failures, attempted = [], set()
    maximum = min(8, max(1, int(settings.get("max_products_per_run", 4))))
    for keyword in settings["keywords"]:
        siblings = api.search(keyword)
        for product in siblings:
            if product["product_id"] in attempted or ledger.seen(product, products):
                continue
            attempted.add(product["product_id"])
            if len(attempted) > maximum:
                break
            eid_dir = ROOT / "current_episode" / fingerprint({"product_id": product["product_id"], "version": 1})[:24]
            eid_dir.mkdir(parents=True, exist_ok=True)
            try:
                product["affiliate_link"] = api.deeplink(product)
                atomic_json(eid_dir / "product.json", product)
                assets = collect(ai, product, siblings, settings, eid_dir, for_publication=publish)
            except GateError as exc:
                failures.append({"product_id": product["product_id"], "error": str(exc)})
                atomic_json(ROOT / "current_episode" / "selection_failures.json", failures)
                continue
            episode = ledger.reserve(product, ledger.next_number(products))
            if run_key:
                ledger.data["plans"][run_key] = episode["id"]
            ledger.update(episode, artifact_run_id=os.getenv("GITHUB_RUN_ID"), artifact_run_attempt=os.getenv("GITHUB_RUN_ATTEMPT", "1"))
            prepare_episode(ai, ledger, episode, assets, settings, eid_dir)
            return episode
        if len(attempted) >= maximum:
            break
    raise GateError("No product supplied three distinct, exact-match scenes; no catalogue entry or video published")


def main():
    parser = argparse.ArgumentParser()
    phases = parser.add_mutually_exclusive_group()
    phases.add_argument("--prepare", action="store_true")
    phases.add_argument("--register-catalogue", action="store_true")
    phases.add_argument("--release", action="store_true")
    parser.add_argument("--publish", action="store_true", help="Use only reusable media; release is a separate phase")
    parser.add_argument("--episode", default="")
    args = parser.parse_args()
    settings = json.loads((ROOT / "shopping_config.json").read_text(encoding="utf-8"))
    remote = os.getenv("GITHUB_ACTIONS") == "true"
    ledger = Ledger(remote=remote)
    if args.register_catalogue or args.release:
        if not remote or ledger.branch != "main" or not re.fullmatch(r"[a-f0-9]{24}", args.episode):
            raise GateError("Release requires a durable main-branch episode ID")
        episode = ledger.data["episodes"][args.episode]
        directory = ROOT / "current_episode" / episode["id"]
        if not (directory / "final_shorts.mp4").exists():
            restore(ledger, episode, directory)
        verified_files(episode, directory)
        if args.register_catalogue:
            register(ledger, episode, directory, settings["catalogue_base_url"])
            export_site(ledger)
        else:
            publisher = Publisher(ledger, catalogue_gate=lambda row: verify_live(row, settings["catalogue_base_url"]))
            video_id = publisher.publish(episode, directory / "final_shorts.mp4", directory / "thumbnail.jpg")
            print("Published: https://www.youtube.com/watch?v=" + video_id)
    else:
        episode = prepare(ledger, settings, args.publish)
        if episode["status"] == "published":
            output(ready="false", episode_id=episode["id"])
            print("This run already published its episode; no additional upload")
            return
        output(ready="true", episode_id=episode["id"])
        print(f"All quality gates passed: catalog NO.{episode['catalogue_id']}; episode {episode['id']}")
        print("This preparation phase does not upload to YouTube.")


if __name__ == "__main__":
    main()
