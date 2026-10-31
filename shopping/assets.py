"""Match public product media to the exact affiliate product reference.

Unknown review sources can be inspected in previews. Automatic publication uses
affiliate-provided images or source URLs explicitly configured for reuse.
"""
from io import BytesIO
import ipaddress
import json
from pathlib import Path
import re
import socket
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from PIL import Image, ImageOps
import requests

from .ai import image_part
from .core import GateError, AIUnavailable, ROOT, atomic_json, fingerprint, run
from .media import image_hash, probe

BAD_IMAGES = ("1584622650111", "1556911220")


def allowed_source(url, prefixes):
    value = urlparse(url)
    for prefix in prefixes:
        trusted = urlparse(prefix)
        path = trusted.path.rstrip("/")
        if (trusted.scheme == value.scheme == "https" and trusted.netloc == value.netloc
                and (value.path == path or value.path.startswith(path + "/"))):
            return True
    return False


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.port not in (None, 443) or not parsed.hostname:
        raise GateError("Media must use a public HTTPS URL")
    host = parsed.hostname.lower()
    if host in ("localhost", "images.unsplash.com", "picsum.photos", "via.placeholder.com"):
        raise GateError("Generic stock/placeholder/private media is not a product reference")
    for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(item[4][0]).is_global:
            raise GateError("Private network media URL is not permitted")
    return url


def fetch(url, cap=12_000_000):
    for _ in range(6):
        public_url(url)
        response = requests.get(url, headers={"User-Agent": "ProductShorts/2.0"},
                                timeout=(12, 35), allow_redirects=False, stream=True)
        with response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if response.status_code != 200:
                raise GateError(f"Public media returned HTTP {response.status_code}")
            content = bytearray()
            for block in response.iter_content(65536):
                content.extend(block)
                if len(content) > cap:
                    raise GateError("Public media exceeds download limit")
            return bytes(content), url, response.headers.get("Content-Type", "")
    raise GateError("Too many media redirects")


def save_image(url, target, minimum=350):
    if any(value in url for value in BAD_IMAGES):
        raise GateError("Known negative-control image is blocked")
    # The affiliate CDN supports resizing the same authentic source image.
    upgraded = re.sub(r"/remote/\d+x\d+ex/", "/remote/1080x1080ex/", url) if "coupangcdn.com/" in url else url
    try:
        content, resolved, _ = fetch(upgraded, 20_000_000)
    except GateError:
        content, resolved, _ = fetch(url, 20_000_000)
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        if min(image.size) < minimum or image.width * image.height > 35_000_000:
            raise GateError("Product image resolution invalid")
        image.save(target, "JPEG", quality=95)
    return resolved


def parse_page(content, page_url):
    soup = BeautifulSoup(content, "html.parser")
    found = []
    for tag in soup.find_all("meta"):
        prop = tag.get("property") or tag.get("name", "")
        if prop in ("og:image", "og:image:secure_url", "og:video", "og:video:url", "og:video:secure_url") and tag.get("content"):
            found.append({"url": urljoin(page_url, tag["content"]), "type": "video" if "video" in prop else "image"})
    for tag in soup.find_all(["video", "source"]):
        if tag.get("src"):
            found.append({"url": urljoin(page_url, tag["src"]), "type": "video"})

    def visit(value):
        if isinstance(value, dict):
            kind = "video" if "VideoObject" in str(value.get("@type")) else "image"
            for key in ("contentUrl", "image", "thumbnailUrl"):
                urls = value.get(key, [])
                for url in urls if isinstance(urls, list) else [urls]:
                    if isinstance(url, str) and url.startswith("https://"):
                        found.append({"url": url, "type": kind if key == "contentUrl" else "image"})
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            visit(json.loads(tag.string or tag.get_text()))
        except ValueError:
            pass
    # Public review page metadata only; no login cookies or private endpoints.
    for match in re.finditer(r'"(masterUrl|videoUrl|urlDefault)"\s*:\s*("(?:\\.|[^"\\])*")', content.decode("utf-8", "replace")):
        try:
            url = json.loads(match.group(2))
            if url.startswith("https://"):
                found.append({"url": url, "type": "image" if match.group(1) == "urlDefault" else "video"})
        except ValueError:
            continue
    return found[:24]


def discover(ai, product, siblings, settings, directory):
    candidates = []
    registry_file = ROOT / "product_sources.json"
    registry = json.loads(registry_file.read_text(encoding="utf-8")) if registry_file.exists() else []
    for row in registry:
        if str(row.get("product_id")) == product["product_id"]:
            for item in row.get("media", []):
                candidates.append({**item, "source_title": product["title"], "source_url": item.get("source_url", item["url"]),
                                   "publication_allowed": item.get("publication_allowed") is True})
    try:
        body, page, content_type = fetch(product["canonical_url"], 8_000_000)
        if "html" in content_type.lower():
            for item in parse_page(body, page):
                candidates.append({**item, "source_url": page, "source_title": product["title"],
                                   "publication_allowed": True, "official_api": True})
            soup = BeautifulSoup(body, "html.parser")
            for tag in soup.find_all("img"):
                url = urljoin(page, tag.get("data-src") or tag.get("src") or "")
                if (urlparse(url).hostname or "").endswith(".coupangcdn.com"):
                    candidates.append({"url": url, "type": "image", "source_url": page,
                        "source_title": product["title"], "publication_allowed": True, "official_api": True})
    except (GateError, requests.RequestException, OSError, ValueError):
        pass
    try:
        result = ai.search("Find original publicly accessible overseas user demonstrations "
            "and manufacturer/seller media pages for this EXACT product, not generic examples. Include Xiaohongshu "
            "if relevant and official product pages. Do not invent URLs or substitute another model/color. "
            "Return original source pages with citations. Product: " + product["title"])
        atomic_json(directory / "media_search.json", result)
        for source in result.get("sources", [])[:5]:
            page = source.get("url")
            if not page:
                continue
            try:
                body, resolved, content_type = fetch(page, 5_000_000)
                if "html" not in content_type.lower():
                    continue
                approved = allowed_source(resolved, settings.get("approved_review_url_prefixes", []))
                for item in parse_page(body, resolved):
                    candidates.append({**item, "source_url": resolved, "source_title": source.get("title", ""),
                                       "publication_allowed": approved})
            except (GateError, requests.RequestException, OSError, ValueError):
                continue
    except GateError as exc:
        atomic_json(directory / "search_failure.json", {"error": str(exc)})
        if isinstance(exc, AIUnavailable):
            raise
    # Official affiliate API images are the fallback, not unrelated stock photos.
    for row in [product] + siblings:
        candidates.append({"url": row["reference_image"], "type": "image", "source_url": row["canonical_url"],
                           "source_title": row["title"], "publication_allowed": True, "official_api": True})
    candidates.sort(key=lambda c: c.get("type") != "video")
    return candidates


def validate_product_media(ai, product, reference, files, source_title):
    prompt = ("Compare the CANDIDATE media against the TARGET reference and exact product title. "
        "Only PASS when the same physical product model, color/variant, shape, connectors and distinguishing "
        "features are clearly visible as the main subject in ALL candidate frames. A generic faucet/kitchen "
        "is insufficient. Cooking people, pots, toilets and room interiors are REJECT even if the product "
        "appears faintly in the background. Text-confirmed different models are REJECT. Unknown identity is UNKNOWN. "
        "The TARGET is identity evidence, not a second candidate.\nTARGET TITLE: " + product["title"]
        + "\nCANDIDATE SOURCE TITLE: " + source_title)
    attachments = [{"text": "TARGET reference for identity only"}, image_part(reference)]
    for file in files:
        attachments += [{"text": "CANDIDATE: check the product in this frame"}, image_part(file)]
    return ai.judge(prompt, ["same_model", "same_variant", "clear_main_subject", "no_unrelated_stock"], attachments)


def collect(ai, product, siblings, settings, directory, for_publication=False):
    reference = directory / "reference.jpg"
    save_image(product["reference_image"], reference, minimum=180)
    candidates = discover(ai, product, siblings, settings, directory)
    print(f'[media] Discovered {len(candidates)} candidate assets for product {product["product_id"]}',flush=True)
    approved, hashes, used, attempts = [], [], set(), []
    for candidate in candidates[:32]:
        url = candidate["url"]
        if url in used or (for_publication and not candidate.get("publication_allowed")):
            continue
        used.add(url)
        print(f'[media] Inspect candidate {len(used)}; approved scenes {len(approved)}/3',flush=True)
        try:
            if candidate["type"] == "video":
                if urlparse(url).path.lower().endswith(".m3u8"):
                    raise GateError("Streaming playlists are not downloaded as video files")
                body, _, content_type = fetch(url, 80_000_000)
                if "html" in content_type.lower():
                    raise GateError("Review download returned a page instead of video")
                original = directory / ("source_" + fingerprint(url)[:12] + ".mp4")
                original.write_bytes(body)
                metadata = json.loads(run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                    "-show_format", "-of", "json", str(original)]).stdout)
                total = float(metadata["format"]["duration"])
                if not 4 <= total <= 600:
                    raise GateError("Review duration outside supported limits")
                for fraction in (.05, .37, .69):
                    number = len(approved) + 1
                    start, length = total * fraction, min(4, total * .25)
                    clip = directory / f"scene_{number:02d}.mp4"
                    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-protocol_whitelist", "file,pipe",
                         "-ss", str(start), "-i", str(original), "-t", str(length), "-an", "-c:v", "libx264",
                         "-preset", "fast", str(clip)])
                    frames = []
                    for index, at in enumerate((.05, length / 2, length - .1)):
                        frame = directory / f"candidate_{number}_{index}.jpg"
                        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(at), "-i", str(clip),
                             "-frames:v", "1", str(frame)])
                        frames.append(frame)
                    dhash = image_hash(frames[1])
                    if any((dhash ^ old).bit_count() <= 5 for old in hashes):
                        continue
                    report = validate_product_media(ai, product, reference, frames, candidate.get("source_title", ""))
                    poster = directory / f"scene_{number:02d}.jpg"
                    poster.write_bytes(frames[1].read_bytes())
                    approved.append({**candidate, "kind": "video", "start": start, "length": length,
                                     "poster": poster.name, "clip": clip.name, "review": report})
                    hashes.append(dhash)
                    if len(approved) == 3:
                        break
            else:
                number = len(approved) + 1
                image = directory / f"scene_{number:02d}.jpg"
                save_image(url, image)
                if candidate.get('crop'):
                    with Image.open(image) as original:
                        box = candidate['crop']
                        if (not isinstance(box,list) or len(box)!=4 or any(type(n) is not int for n in box)
                                or not (0<=box[0]<box[2]<=original.width and 0<=box[1]<box[3]<=original.height)
                                or min(box[2]-box[0],box[3]-box[1])<350):
                            raise GateError('Invalid source-photo crop')
                        cropped=original.crop(box)
                    cropped.save(image,'JPEG',quality=95)
                dhash = image_hash(image)
                if any((dhash ^ old).bit_count() <= 5 for old in hashes):
                    continue
                report = validate_product_media(ai, product, reference, [image], candidate.get("source_title", ""))
                approved.append({**candidate, "kind": "image", "poster": image.name, "review": report})
                hashes.append(dhash)
            attempts.append({"url": url, "outcome": "checked"})
        except AIUnavailable:
            raise
        except (GateError, requests.RequestException, OSError, ValueError, KeyError) as exc:
            attempts.append({"url": url, "outcome": "rejected", "error": str(exc)[:500] if isinstance(exc, GateError) else type(exc).__name__})
        if len(approved) == 3:
            break
    atomic_json(directory / "media_attempts.json", attempts)
    print(f'[media] Exact-match distinct scenes: {len(approved)}/3',flush=True)
    if len(approved) != 3:
        raise GateError(f"Only {len(approved)} distinct matching product scenes found; no cloning or stock fallback")
    atomic_json(directory / "assets.json", approved)
    return approved
