"""Real product media, fixed banners and separate timed narration captions."""
import json
import math
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageEnhance

from .ai import image_part, PRODUCT_IDENTITY_RULES
from .core import GateError, atomic_json, fingerprint, run
from . import media

DISCLOSURE = "쿠팡 파트너스 활동으로 일정액의 수수료를 제공받습니다."


def banner(canvas, text, y, size, color, background, max_lines=2):
    face = ImageFont.truetype(media.font_path(), size)
    lines, line = [], ""
    for char in text:
        if char == "\n" or face.getlength(line + char) > 940:
            lines.append(line)
            line = "" if char == "\n" else char
        else:
            line += char
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        raise GateError("Overlay text exceeds its designated safe region")
    draw = ImageDraw.Draw(canvas)
    height = round(size * 1.4)
    draw.rounded_rectangle((35, y - 15, 1045, y + height * len(lines) + 15), radius=18, fill=background)
    for index, value in enumerate(lines):
        draw.text(((1080 - face.getlength(value)) / 2, y + height * index), value, font=face, fill=color)


def overlay(scene):
    image = Image.new("RGBA", (1080, 1920))
    banner(image, scene["badge"], 180, 48, "black", (255, 215, 0, 240), 1)
    banner(image, scene["hook"], 290, 66, "white", (0, 0, 0, 200))
    banner(image, scene["sub"], 1520, 52, (0, 255, 200, 255), (0, 0, 0, 215), 1)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 1640, 1080, 1830), fill=(12, 18, 26, 245))
    face = ImageFont.truetype(media.font_path(), 25)
    draw.text(((1080 - face.getlength(DISCLOSURE)) / 2, 1855), DISCLOSURE, font=face, fill="white")
    return image


def compose(source, scene):
    background = ImageOps.fit(source.convert("RGB"), (1080, 1920)).filter(ImageFilter.GaussianBlur(28))
    background = ImageEnhance.Brightness(background).enhance(.30).convert("RGBA")
    foreground = ImageOps.contain(source.convert("RGB"), (1000, 900), Image.Resampling.LANCZOS)
    background.paste(foreground, ((1080 - foreground.width) // 2, 550 + (900 - foreground.height) // 2))
    background.alpha_composite(overlay(scene))
    return background.convert("RGB")


def render(meta, directory, timings):
    profile = media.PROFILES["shorts"]
    lengths, narration_lengths, all_cues, elapsed = [], [], [], 0.0
    if len(meta["scenes"]) != 3 or len(timings) != 3:
        raise GateError("Exactly three separately verified scenes and voices required")
    for scene, boundaries in zip(meta["scenes"], timings):
        n = scene["scene_num"]
        audio = directory / f"voice_{n:02d}.mp3"
        dur = media.duration(audio)
        length = math.ceil(dur * 30) / 30
        media.validate_boundaries(boundaries, scene["narration"], dur)
        cues = media.caption_cues(boundaries, profile)
        media.write_ass(directory / f"captions_{n:02d}.ass", cues, profile)
        with Image.open(directory / f"scene_{n:02d}.jpg") as source:
            compose(source, scene).save(directory / f"framed_{n:02d}.jpg", quality=95)
        if scene["media_kind"] == "video":
            overlay(scene).save(directory / f"overlay_{n:02d}.png")
            inputs = ["-stream_loop", "-1", "-i", f"scene_{n:02d}.mp4", "-loop", "1", "-i", f"overlay_{n:02d}.png", "-i", audio.name]
            filters = ("[0:v]split=2[bg][fg];"
                "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=28:2,eq=brightness=-0.25[b];"
                "[fg]scale=1000:900:force_original_aspect_ratio=decrease,setsar=1[f];"
                "[b][f]overlay=(W-w)/2:550+(900-h)/2[base];"
                f"[base][1:v]overlay=0:0,subtitles=filename=captions_{n:02d}.ass,fps=30[v]")
            mapping = ["-filter_complex", filters, "-map", "[v]", "-map", "2:a:0"]
        elif scene["media_kind"] == "image":
            inputs = ["-loop", "1", "-framerate", "30", "-i", f"framed_{n:02d}.jpg", "-i", audio.name]
            mapping = ["-vf", f"subtitles=filename=captions_{n:02d}.ass", "-map", "0:v:0", "-map", "1:a:0"]
        else:
            raise GateError("Unrecognized media kind; never use a stale rejected clip")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, *mapping,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30", "-fps_mode", "cfr",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-af", "apad", "-t", f"{length:.6f}", f"clip_{n:02d}.mp4"], cwd=directory, timeout=900)
        all_cues.extend({**c, "start": c["start"] + elapsed, "end": c["end"] + elapsed} for c in cues)
        lengths.append(length)
        narration_lengths.append(dur)
        elapsed += length
    (directory / "concat.txt").write_text("".join(f"file 'clip_{n:02d}.mp4'\nduration {d:.9f}\n" for n, d in enumerate(lengths, 1)), encoding="utf-8")
    final = directory / "final_shorts.mp4"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt",
        "-vf", "fps=30", "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-af", "aresample=async=1:first_pts=0", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", final.name], cwd=directory, timeout=900)
    (directory / "subtitles.srt").write_text("".join(f"{i}\n{media.timestamp(c['start'])} --> {media.timestamp(c['end'])}\n" + "\n".join(c["lines"]) + "\n\n" for i, c in enumerate(all_cues, 1)), encoding="utf-8")
    manifest = {"profile": profile.__dict__, "scene_durations": lengths, "narration_durations": narration_lengths,
        "cues": all_cues, "sha256": fingerprint(final.read_bytes())}
    atomic_json(directory / "render_manifest.json", manifest)
    return final, manifest


def review(ai, meta, video, manifest, directory):
    samples, elapsed = [], 0.0
    for scene, length in zip(meta["scenes"], manifest["scene_durations"]):
        n = scene["scene_num"]
        for fraction in (.15, .5, .85):
            at = elapsed + length * fraction
            frame = directory / f"review_{n}_{int(fraction*100)}.jpg"
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(at), "-i", str(video), "-frames:v", "1", str(frame)])
            crop = directory / "caption_crop.jpg"
            with Image.open(frame) as source:
                source.crop((0, 1635, 1080, 1835)).save(crop)
            expected = next((c["lines"] for c in manifest["cues"] if c["start"] <= at < c["end"]), [])
            result = ai.json('Transcribe ONLY the visible Korean subtitle. Do not infer missing text. Return {"subtitle_text":""}.',
                [image_part(crop)], review=True, schema={"type": "OBJECT", "required": ["subtitle_text"], "properties": {"subtitle_text": {"type": "STRING"}}})
            media.compare_subtitle_text(expected, result["subtitle_text"])
            verdict = ai.judge("Review this ACTUAL encoded shopping frame against TARGET product reference. "
                "Product must remain identifiable in the sharp central media window; ignore the decorative blurred background. "
                "All banners and current caption fragment must be legible, within bounds and separated from the product. "
                "Timed captions intentionally show only the CURRENT fragment, not the entire narration. "
                + PRODUCT_IDENTITY_RULES
                + json.dumps({"title": meta["product_title"], "scene": {k: scene[k] for k in ("badge", "hook", "sub")}, "current_caption": expected}, ensure_ascii=False),
                ["product_identity", "legibility", "safe_bounds", "no_obscured_product"],
                [{"text": "TARGET reference"}, image_part(directory / "reference.jpg"), {"text": "ENCODED FRAME"}, image_part(frame)])
            samples.append({"at": at, "ocr": result, "review": verdict})
            atomic_json(directory / "render_review.json", samples)
        elapsed += length
    return samples


def thumbnail(ai, meta, directory):
    scene = {**meta["scenes"][0], "hook": meta["thumbnail_text"]}
    with Image.open(directory / "scene_01.jpg") as source:
        image = compose(source, scene)
    path = directory / "thumbnail.jpg"
    image.save(path, quality=85)
    result = ai.judge("Check shopping thumbnail: real product matches TARGET, intended main hook is exact, "
        "legible, uncut, and supported by product title. " + PRODUCT_IDENTITY_RULES + json.dumps({"hook": meta["thumbnail_text"], "product": meta["product_title"]}, ensure_ascii=False),
        ["product_identity", "correct_hook", "legibility", "truthful_claims"],
        [{"text": "TARGET reference"}, image_part(directory / "reference.jpg"), {"text": "THUMBNAIL"}, image_part(path)])
    atomic_json(directory / "thumbnail_review.json", {**result, "sha256": fingerprint(path.read_bytes())})
    return path
