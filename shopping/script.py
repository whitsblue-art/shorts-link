import json
import re

from .core import GateError, AIUnavailable, atomic_json, normalize
from .ai import image_part, PRODUCT_IDENTITY_RULES

STYLE_VERSION = 3


def visual_evidence(meta, directory):
    parts = []
    for scene in meta['scenes']:
        n = scene['scene_num']
        parts.append({'text': f'ACTUAL SCENE {n}: narration must describe only what this footage shows.'})
        frames = sorted(directory.glob(f'evidence_{n:02d}_*.jpg')) or [directory/f'scene_{n:02d}.jpg']
        parts.extend(image_part(f) for f in frames)
    return parts


FORBIDDEN = ("최저가", "100%", "무조건", "완벽하게", "제가 써", "직접 써", "직접 사용", "완치", "치료")


def validate(meta, number):
    if not isinstance(meta, dict) or not 1 <= len(meta.get("title", "")) <= 100:
        raise GateError("Invalid shopping video title")
    if not isinstance(meta.get("thumbnail_text"), str) or not 1 <= len(meta["thumbnail_text"]) <= 24:
        raise GateError("Invalid thumbnail hook")
    scenes = meta.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 3:
        raise GateError("Shopping video must have exactly three scenes")
    for index, scene in enumerate(scenes, 1):
        if scene.get("scene_num") != index or type(scene.get("scene_num")) is not int:
            raise GateError("Scene numbering invalid")
        for key in ("narration", "badge", "hook", "sub", "visual_prompt"):
            if not isinstance(scene.get(key), str) or not scene[key].strip():
                raise GateError("Shopping scene field missing")
        lower, upper = (20, 115) if meta.get('style_version') == STYLE_VERSION else (50, 140)
        if not lower <= len(scene["narration"]) <= upper:
            raise GateError(f'Shopping narration must be {lower}~{upper} characters per scene')
        if len(scene["badge"]) > 24 or len(scene["hook"]) > 35 or len(scene["sub"]) > 42:
            raise GateError("Shopping overlay text is too long")
    all_text = json.dumps(meta, ensure_ascii=False)
    if any(word in all_text for word in FORBIDDEN):
        raise GateError("Unsupported superlative, medical or first-hand testimonial claim")
    last = scenes[-1]
    if f"{number}번" not in last["sub"] or f"{number}번" not in last["narration"] or "프로필" not in last["narration"]:
        raise GateError("CTA must direct viewers to the exact catalog number in the profile link")
    if meta.get('style_version') == STYLE_VERSION:
        spoken = ''.join(s['narration'] for s in scenes)
        if spoken.count('프로필') != 1 or any('프로필' in s['narration']+s['hook']+s['sub'] for s in scenes[:-1]):
            raise GateError('Profile CTA is permitted only once, at the end')
        if sum(map(len, [s['narration'] for s in scenes])) > 270:
            raise GateError('Usage narration is too long')
        if any(s.get('media_kind') != 'video' for s in scenes):
            raise GateError('Usage style requires real moving demonstration footage')
    if len({normalize(s["narration"]) for s in scenes}) != 3:
        raise GateError("Scene narration is duplicated")
    from .design import overlay
    for scene in scenes:
        overlay(scene)  # Measure actual Korean glyphs before accepting a script.
    return meta


def review(ai, product, number, meta, directory=None):
    usage = meta.get('style_version') == STYLE_VERSION
    if usage and directory is None:
        raise GateError('Usage script review requires actual scene footage')
    return ai.judge('Audit this advertisement against the affiliate product title AND the labelled actual scene frames. Every feature must '
        'be supported; reject invented performance, compatibility, pricing, health benefits or personal testing. '
        'Distinguish an entire faucet from a replacement filter HEAD: never describe a head as the whole faucet. '
        'Each spoken action must match its OWN scene. An ordinary demonstration must not become an invented surprising use. '
        'Reject repetitive shopping instructions, catalogue-like filler, or an unnatural read-aloud script. '
        'Only one brief spoken profile CTA, at the very end. Do not require spare filters in every scene. '
        + PRODUCT_IDENTITY_RULES + 'Check the exact profile/catalog number.\n' + json.dumps({'product_title':product['title'],
            'catalog_number':number,'script':meta},ensure_ascii=False),
        ['supported_claims','no_fake_testimonial','truthful_hook','correct_catalog_cta'] + (['scene_action_alignment','correct_product_noun','natural_story','single_cta'] if usage else []),
        visual_evidence(meta,directory) if usage else [])


def generate(ai, product, number, assets, directory):
    string = {"type": "STRING"}
    scene = {"type": "OBJECT", "required": ["scene_num", "narration", "badge", "hook", "sub", "visual_prompt"],
        "properties": {"scene_num": {"type": "INTEGER"}, **{k: string for k in ("narration", "badge", "hook", "sub", "visual_prompt")}}}
    schema = {"type": "OBJECT", "required": ["title", "description", "thumbnail_text", "scenes"],
        "properties": {"title": string, "description": string, "thumbnail_text": string,
                       "scenes": {"type": "ARRAY", "minItems": 3, "maxItems": 3, "items": scene}}}
    prompt = (
        'Write an engaging Korean real-use demonstration Short, about 20~27 seconds. Exactly three chapters, '
        'total 180~240 Korean characters, each 20~100 characters. Short conversational sentences, lively but not shouty. '
        'Hook with what the ACTUAL footage shows, then explain the visible action, then result and ONE brief final CTA. '
        'No polite catalogue lecture, no repeated 상세페이지/호환/구성 확인 filler. No fabricated viral trends, hidden uses, '
        'before-after results or performance. Match EACH narration to its labelled scene frames. '
        'A filter HEAD is not a whole faucet. Use precise everyday product nouns; do not merely recite the listing title. '
        'Describe only visibly demonstrated actions and title-supported facts. No health, purification efficiency or lowest-price claims. '
        f'Only the final narration ends with "제품은 프로필 링크에서 {number}번."; never mention the profile earlier. '
        f'Last sub is "프로필 링크에서 [{number}번] 검색!". Other sub/badge may describe the action, not shopping instructions. '
        'Hook/thumbnail_text <=22 Korean chars; badge <=15; sub <=18 except final fixed CTA. '
        'Title is a truthful, specific curiosity hook, reused as the video headline. visual_prompt describes actual action only. '
        'Return JSON. Product: '+json.dumps(product['title'],ensure_ascii=False)
    )
    placeholders={'scenes':[{'scene_num':i} for i in range(1,4)]}
    evidence=visual_evidence(placeholders,directory)
    feedback = ""
    for attempt in range(2):
        meta = ai.json(prompt + feedback, evidence, schema=schema)
        meta['style_version']=STYLE_VERSION
        for row, asset in zip(meta['scenes'],assets):
            row['media_kind']=asset['kind']
            row['media_fit']=asset.get('fit','cover')
        atomic_json(directory / f"script_draft_{attempt+1}.json", meta)
        try:
            validate(meta, number)
            verdict = review(ai, product, number, meta, directory)
            for row, asset in zip(meta["scenes"], assets):
                row["media_kind"] = asset["kind"]
            atomic_json(directory / "script_review.json", verdict)
            atomic_json(directory / "meta.json", meta)
            return meta
        except AIUnavailable:
            raise
        except GateError as exc:
            if attempt:
                raise
            feedback = "\nRepair the complete JSON: " + str(exc)
