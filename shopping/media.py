import asyncio
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import unicodedata
from fractions import Fraction

import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat, ImageFilter, ImageEnhance

from .ai import image_part, review_audio
from .core import GateError, atomic_json, fingerprint, normalize, require_pass, run


@dataclass(frozen=True)
class Profile:
    width: int
    height: int
    fps: int
    minimum: float
    maximum: float


PROFILES = {"shorts": Profile(1080, 1920, 30, 25, 120),
            "longform": Profile(1920, 1080, 30, 300, 900)}


def preflight():
    for name in ("ffmpeg", "ffprobe"):
        if not shutil.which(name):
            raise GateError(f"Missing {name}")
    font_path()
    filters = run(["ffmpeg", "-hide_banner", "-filters"]).stdout
    if "subtitles" not in filters or "loudnorm" not in filters:
        raise GateError("FFmpeg requires libass subtitles and loudnorm")


def font_path():
    for path in (os.getenv("KOREAN_FONT", ""),
                 "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "C:/Windows/Fonts/malgunbd.ttf"):
        if path and Path(path).is_file():
            return path
    raise GateError("Korean font is required; install fonts-nanum or set KOREAN_FONT")


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]).stdout)


def duration(path):
    value = float(probe(path)["format"]["duration"])
    if not math.isfinite(value) or value <= 0:
        raise GateError("Empty or invalid media duration")
    return value


def image_hash(path):
    with Image.open(path) as image:
        pixels = list(image.convert("L").resize((9, 8)).getdata())
    return sum((pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
               for y in range(8) for x in range(8))




def validate_boundaries(boundaries, narration, audio_duration):
    if not boundaries:
        raise GateError("TTS returned no word timing; guessed subtitle timing is disallowed")
    previous = -1.0
    for boundary in boundaries:
        start, end = boundary["start"], boundary["end"]
        if not all(math.isfinite(x) for x in (start, end)) or start < previous or end <= start or end > audio_duration + 0.25:
            raise GateError("Invalid TTS boundary timing")
        previous = start
    combined = normalize("".join(b["text"] for b in boundaries))
    if combined != normalize(narration):
        raise GateError("TTS word timing does not cover the full narration")


async def make_voice(narration, raw, kind):
    boundaries = []
    speech = edge_tts.Communicate(narration, voice=os.getenv("TTS_VOICE", "ko-KR-SunHiNeural"),
        rate="+15%" if kind == "shorts" else "+0%", pitch="+0Hz", boundary="WordBoundary")
    with raw.open("wb") as handle:
        async for chunk in speech.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                boundaries.append({"text": chunk["text"], "start": chunk["offset"] / 10_000_000,
                                   "end": (chunk["offset"] + chunk["duration"]) / 10_000_000})
    if not raw.is_file() or raw.stat().st_size == 0:
        raise GateError("TTS returned empty audio")
    validate_boundaries(boundaries, narration, duration(raw))
    return boundaries


def audio_quality(path, maximum_silence=1.2):
    result = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
        "silencedetect=noise=-40dB:d=0.7,volumedetect", "-f", "null", "-"])
    log = result.stderr
    mean = re.search(r"mean_volume: (-?[\d.]+|inf|-inf) dB", log)
    if not mean or float(mean.group(1)) < -38:
        raise GateError("Narration is absent or too quiet")
    silences = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", log)]
    if any(x > maximum_silence for x in silences):
        raise GateError("Narration contains excessive silence")
    return {"mean_db": float(mean.group(1)), "silences": silences, "duration": duration(path)}


def trim_voice_edges(raw, clean, boundaries):
    """Trim outer padding only; retain every timed word and audible phoneme."""
    raw_duration = duration(raw)
    log = run(["ffmpeg", "-hide_banner", "-i", str(raw), "-af",
               "silencedetect=noise=-45dB:d=0.08", "-f", "null", "-"]).stderr
    events = re.findall(r"silence_(start|end): ([\d.]+)", log)
    leading_end, audible_end, pending = 0.0, raw_duration, None
    for kind, value in events:
        value = float(value)
        if kind == "start":
            pending = value
        elif pending is not None:
            if pending < .01:
                leading_end = value
            if value >= raw_duration - .08:
                audible_end = pending
            pending = None
    start = max(0.0, min(boundaries[0]["start"], leading_end) - .08)
    end = min(raw_duration, max(boundaries[-1]["end"], audible_end) + .15)
    if end <= start or end < boundaries[-1]["end"]:
        raise GateError("Cannot trim voice edges without cutting a word")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-af",
         f"atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5:LRA=11",
         "-ar", "48000", "-ac", "1", str(clean)])
    shifted = [{**b, "start": max(0, b["start"] - start), "end": b["end"] - start} for b in boundaries]
    return shifted, {"version": 1, "removed_leading": start, "kept_until": end,
                     "original_duration": raw_duration, "internal_pauses_removed": False}


def generate_voices(ai, meta, kind, directory):
    times = []
    for scene in meta["scenes"]:
        number = scene["scene_num"]
        raw = directory / f"voice_raw_{number:02d}.mp3"
        clean = directory / f"voice_{number:02d}.mp3"
        timing_path = directory / f"timings_{number:02d}.json"
        raw_timing_path = directory / f"tts_timings_{number:02d}.json"
        report_path = directory / f"audio_review_{number:02d}.json"
        prior = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
        narration_hash = fingerprint(scene["narration"])
        reusable = (clean.is_file() and timing_path.is_file() and prior.get("edge_trim", {}).get("version") == 1
                    and prior.get("narration_sha256") == narration_hash
                    and prior.get("speech", {}).get("sha256") == fingerprint(clean.read_bytes())
                    and prior.get("speech", {}).get("semantic_review", {}).get("verdict") == "PASS")
        if reusable:
            boundaries = json.loads(timing_path.read_text(encoding="utf-8"))
            trim_report = prior["edge_trim"]
        else:
            if raw.is_file() and raw_timing_path.is_file():
                raw_boundaries = json.loads(raw_timing_path.read_text(encoding="utf-8"))
            elif raw.is_file() and timing_path.is_file() and not prior.get("edge_trim"):
                raw_boundaries = json.loads(timing_path.read_text(encoding="utf-8"))
            else:
                raw_boundaries = asyncio.run(make_voice(scene["narration"], raw, kind))
            validate_boundaries(raw_boundaries, scene["narration"], duration(raw))
            atomic_json(raw_timing_path, raw_boundaries)
            boundaries, trim_report = trim_voice_edges(raw, clean, raw_boundaries)
            atomic_json(timing_path, boundaries)
        validate_boundaries(boundaries, scene["narration"], duration(clean))
        report = prior if reusable else {"signal": audio_quality(clean), "speech": review_audio(ai, clean, scene["narration"])}
        atomic_json(report_path, {**report, "narration_sha256": narration_hash, "edge_trim": trim_report})
        times.append(boundaries)
    return times


def caption_cues(boundaries, profile):
    face = ImageFont.truetype(font_path(), round(profile.height * (0.023 if profile.height > profile.width else 0.048)))
    max_width = profile.width * 0.82
    cues, lines, current, start, end = [], [], "", None, None
    for word in boundaries:
        text = word["text"].replace("\n", " ")
        if not text.strip():
            continue
        if ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(text, font=face) > max_width:
            raise GateError("A subtitle token is wider than the safe area")
        candidate = (current + " " + text).strip()
        if face.getlength(candidate) > max_width:
            lines.append(current)
            current = ""
            if len(lines) == 2:
                cues.append({"start": start, "end": end, "lines": lines})
                start, lines = None, []
        if start is None:
            start = word["start"]
        current = (current + " " + text).strip()
        end = word["end"]
    if current:
        lines.append(current)
    if lines:
        cues.append({"start": start, "end": end, "lines": lines})
    if not cues:
        raise GateError("No subtitle cues")
    for index, cue in enumerate(cues):
        # Keep each caption visible until the next actual spoken boundary.
        cue["end"] = cues[index + 1]["start"] if index + 1 < len(cues) else cue["end"]
        if cue["end"] - cue["start"] < 0.35:
            raise GateError("Subtitle changes too fast to read")
    return cues


def timestamp(seconds, ass=False):
    ticks = round(seconds * (100 if ass else 1000))
    base = 100 if ass else 1000
    hours, ticks = divmod(ticks, 3600 * base)
    minutes, ticks = divmod(ticks, 60 * base)
    seconds, fraction = divmod(ticks, base)
    return f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}" if ass else f"{hours:02}:{minutes:02}:{seconds:02},{fraction:03}"


def write_ass(path, cues, profile):
    font = ImageFont.truetype(font_path(), 40).getname()[0]
    size = round(profile.height * (0.023 if profile.height > profile.width else 0.048))
    margin = round(profile.height * (0.08 if profile.height > profile.width else 0.10))
    text = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {profile.width}
PlayResY: {profile.height}
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H60000000,&H60000000,-1,0,0,0,100,100,0,0,3,5,0,2,60,60,{margin},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    for cue in cues:
        safe = [line.replace("\\", "").replace("{", "(").replace("}", ")") for line in cue["lines"]]
        caption = r"\N".join(safe)
        text += f"Dialogue: 0,{timestamp(cue['start'], True)},{timestamp(cue['end'], True)},Default,,0,0,0,,{caption}\n"
    path.write_text(text, encoding="utf-8")


def compose_frame(source, profile):
    """Keep all illustration content above a dedicated subtitle panel.

    At the maximum 1.06x zoom the foreground still ends above 0.72H,
    so subtitles cannot obscure a face or a diagram in any frame.
    """
    size = (profile.width, profile.height)
    background = ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    background = ImageEnhance.Brightness(background.filter(ImageFilter.GaussianBlur(28))).enhance(.35)
    foreground = ImageOps.contain(source.convert("RGB"),
        (round(profile.width * .96), round(profile.height * .66)), method=Image.Resampling.LANCZOS)
    background.paste(foreground, ((profile.width - foreground.width) // 2, round(profile.height * .03)))
    return background


def render(meta, kind, directory, timings, profile=None):
    profile = profile or PROFILES[kind]
    scenes = meta["scenes"]
    if len(scenes) != len(timings) or not scenes:
        raise GateError("Scene/timing count mismatch")
    lengths, narration_lengths, all_cues, elapsed = [], [], [], 0.0
    for scene, boundaries in zip(scenes, timings):
        number = scene["scene_num"]
        image, audio = directory / f"scene_{number:02d}.jpg", directory / f"voice_{number:02d}.mp3"
        if not image.is_file() or not audio.is_file():
            raise GateError(f"Scene {number} asset missing; cannot skip it")
        dur = duration(audio)
        clip_duration = math.ceil(dur * profile.fps) / profile.fps
        validate_boundaries(boundaries, scene["narration"], dur)
        cues = caption_cues(boundaries, profile)
        write_ass(directory / f"captions_{number:02d}.ass", cues, profile)
        with Image.open(image) as source:
            compose_frame(source, profile).save(directory / f"framed_{number:02d}.jpg", quality=95)
        vf = (f"zoompan=z='min(max(zoom,pzoom)+0.00025,1.06)':d=1:s={profile.width}x{profile.height}:fps={profile.fps},"
              "drawbox=x=0:y=ih*0.72:w=iw:h=ih*0.28:color=0x10151d@0.98:t=fill,"
              f"subtitles=filename=captions_{number:02d}.ass")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(profile.fps),
            "-i", f"framed_{number:02d}.jpg", "-i", audio.name, "-vf", vf,
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-r", str(profile.fps), "-fps_mode", "cfr",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-af", "apad",
            "-t", f"{clip_duration:.6f}", f"clip_{number:02d}.mp4"], timeout=900, cwd=directory)
        all_cues.extend({**cue, "start": cue["start"] + elapsed, "end": cue["end"] + elapsed} for cue in cues)
        lengths.append(clip_duration)
        narration_lengths.append(dur)
        elapsed += clip_duration
    listing = directory / "concat.txt"
    listing.write_text("".join(f"file 'clip_{s['scene_num']:02d}.mp4'\nduration {d:.9f}\n"
                              for s, d in zip(scenes, lengths)), encoding="utf-8")
    final = directory / f"final_{kind}.mp4"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", listing.name, "-vf", f"fps={profile.fps}", "-fps_mode", "cfr",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
         "-af", "aresample=async=1:first_pts=0", "-c:a", "aac", "-ar", "48000", "-ac", "2",
         "-movflags", "+faststart", final.name], cwd=directory, timeout=900)
    subtitles = "".join(f"{i}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n" + "\n".join(c["lines"]) + "\n\n"
                        for i, c in enumerate(all_cues, 1))
    (directory / "subtitles.srt").write_text(subtitles, encoding="utf-8")
    manifest = {"profile": profile.__dict__, "scene_durations": lengths, "narration_durations": narration_lengths, "cues": all_cues,
                "sha256": fingerprint(final.read_bytes())}
    atomic_json(directory / "render_manifest.json", manifest)
    return final, manifest


def validate_video(path, manifest, profile):
    data = probe(path)
    videos = [s for s in data["streams"] if s["codec_type"] == "video"]
    audios = [s for s in data["streams"] if s["codec_type"] == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise GateError("Final video must have exactly one video and one audio stream")
    stream = videos[0]
    if (stream["width"], stream["height"]) != (profile.width, profile.height):
        raise GateError("Final video dimensions incorrect")
    if abs(float(Fraction(stream["avg_frame_rate"])) - profile.fps) > 0.05:
        raise GateError("Final video frame rate incorrect")
    actual = float(data["format"]["duration"])
    if not profile.minimum <= actual <= profile.maximum:
        raise GateError(f"Final video duration outside approved range: {actual:.1f}s")
    if abs(actual - sum(manifest["scene_durations"])) > 0.8:
        raise GateError("Final video duration does not match all scene narrations")
    if abs(float(stream["duration"]) - float(audios[0]["duration"])) > 0.35:
        raise GateError("Audio and video end times diverge")
    # Decode the whole file, not just ffprobe headers.
    run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], timeout=900)
    black = run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "blackdetect=d=0.2:pix_th=0.10:pic_th=0.99",
                 "-an", "-f", "null", "-"], timeout=900).stderr
    if "black_start:" in black:
        raise GateError("Final video contains black intervals")
    report = {"duration": actual, "signal": audio_quality(path), "sha256": fingerprint(path.read_bytes())}
    return report


def compare_subtitle_text(expected, observed):
    def canonical(value):
        return re.sub(r"\s+", "", unicodedata.normalize("NFC", value).replace("\u200b", ""))
    if canonical(" ".join(expected)) != canonical(observed):
        raise GateError(f"Rendered subtitle characters differ: expected={expected}, observed={observed}")


def review_render(ai, meta, video, manifest, directory):
    elapsed, samples, hashes = 0.0, [], []
    for scene, dur in zip(meta["scenes"], manifest["scene_durations"]):
        at = elapsed + dur / 2
        frame = directory / f"review_frame_{scene['scene_num']:02d}.jpg"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(at), "-i", str(video),
             "-frames:v", "1", "-update", "1", str(frame)])
        with Image.open(frame) as image:
            if sum(ImageStat.Stat(image.convert("RGB")).mean) < 12:
                raise GateError("Sampled final frame is black")
        dhash = image_hash(frame)
        if any((dhash ^ previous).bit_count() <= 2 for previous in hashes):
            raise GateError("Final scenes appear duplicated")
        hashes.append(dhash)
        expected = next((c["lines"] for c in manifest["cues"] if c["start"] <= at < c["end"]), [])
        ocr = ai.json("Read ONLY the large Korean subtitle overlay in this video frame. "
            "Ignore small writing on historical books/documents in the illustration. "
            'Transcribe visible characters without guessing. Return JSON {"subtitle_text":""}; empty if no subtitle.',
            [image_part(frame)], review=True, schema={"type": "OBJECT", "required": ["subtitle_text"],
                "properties": {"subtitle_text": {"type": "STRING"}}})
        compare_subtitle_text(expected, ocr["subtitle_text"])
        review = ai.judge("This is an actual encoded video frame, not a raw illustration. "
            "Check only visual readability, safe bounds, and illustration/narration match. "
            "Subtitle character equality has already been checked by OCR and deterministic code. "
            "This is ONE MOMENT of time-synchronized captions. A caption fragment may end mid-sentence; "
            "later words appear later. Never require the whole sentence in one frame. Readability means "
            "glyph size, contrast and physically uncut letters, NOT sentence completeness. "
            "Do not reject based on spacing or line breaks. Grade the sharp foreground illustration, not "
            "decorative blurred background. Important foreground details must remain visible.\n"
            + json.dumps({"visual_prompt": scene["visual_prompt"], "current_caption_fragment": expected}, ensure_ascii=False),
            ["readability", "safe_bounds", "scene_match"], [image_part(frame)])
        samples.append({"time": at, "subtitle_text": ocr["subtitle_text"], "character_match": True, "review": review})
        elapsed += dur
        atomic_json(directory / "render_review.json", samples)


def thumbnail(ai, meta, kind, directory):
    size = (1080, 1920) if kind == "shorts" else (1920, 1080)
    with Image.open(directory / "scene_01.jpg") as source:
        image = ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS).convert("RGBA")
    overlay = Image.new("RGBA", size)
    draw = ImageDraw.Draw(overlay)
    title = meta["thumbnail_text"].strip()
    # Korean is drawn with a real font, never painted by the image generation model.
    for font_size in range(round(size[0] * 0.09), 39, -2):
        face = ImageFont.truetype(font_path(), font_size)
        lines, current = [], ""
        for char in title:
            if char == "\n" or face.getlength(current + char) > size[0] * 0.84:
                lines.append(current)
                current = "" if char == "\n" else char
            else:
                current += char
        if current:
            lines.append(current)
        if len(lines) <= 3:
            break
    else:
        raise GateError("Thumbnail text cannot fit safely")
    top = round(size[1] * 0.12)
    line_height = round(font_size * 1.4)
    draw.rounded_rectangle((size[0] * .04, top - 25, size[0] * .96, top + len(lines) * line_height + 20),
                           radius=24, fill=(0, 0, 0, 205))
    for index, line in enumerate(lines):
        draw.text(((size[0] - face.getlength(line)) / 2, top + index * line_height), line,
                  font=face, fill=(255, 219, 72), stroke_width=3, stroke_fill="black")
    image.alpha_composite(overlay)
    path = directory / "thumbnail.jpg"
    image.convert("RGB").save(path, quality=90)
    if path.stat().st_size > 2_000_000:
        image.convert("RGB").save(path, quality=75)
    review = ai.judge("Check that this thumbnail matches the documentary and contains exactly the intended "
        "Korean hook without misleading claims or cut-off/illegible text.\n" + json.dumps({"title": meta["title"],
        "hook": title, "facts": meta["facts"]}, ensure_ascii=False),
        ["truthful_relation", "correct_text", "legibility", "safe_bounds"], [image_part(path)])
    atomic_json(directory / "thumbnail_review.json", {**review, "sha256": fingerprint(path.read_bytes())})
    return path


def clean_intermediates(directory):
    for pattern in ("voice_raw_*.mp3", "clip_*.mp4", "framed_*.jpg", "concat.txt"):
        for path in directory.glob(pattern):
            path.unlink()
