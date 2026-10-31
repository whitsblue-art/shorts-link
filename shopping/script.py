import json
import re

from .core import GateError, AIUnavailable, atomic_json, normalize


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
        if not 50 <= len(scene["narration"]) <= 140:
            raise GateError("Shopping narration must be 50~140 characters per scene")
        if len(scene["badge"]) > 24 or len(scene["hook"]) > 35 or len(scene["sub"]) > 42:
            raise GateError("Shopping overlay text is too long")
    all_text = json.dumps(meta, ensure_ascii=False)
    if any(word in all_text for word in FORBIDDEN):
        raise GateError("Unsupported superlative, medical or first-hand testimonial claim")
    last = scenes[-1]
    if f"{number}번" not in last["sub"] or f"{number}번" not in last["narration"] or "프로필" not in last["narration"]:
        raise GateError("CTA must direct viewers to the exact catalog number in the profile link")
    if len({normalize(s["narration"]) for s in scenes}) != 3:
        raise GateError("Scene narration is duplicated")
    from .design import overlay
    for scene in scenes:
        overlay(scene)  # Measure actual Korean glyphs before accepting a script.
    return meta


def review(ai, product, number, meta):
    return ai.judge('Audit this advertisement against ONLY the affiliate product title. Every feature must '
        'be supported; reject invented performance, compatibility, pricing, health benefits or personal testing. '
        'Check the exact profile/catalog number.\n' + json.dumps({'product_title':product['title'],
            'catalog_number':number,'script':meta},ensure_ascii=False),
        ['supported_claims','no_fake_testimonial','truthful_hook','correct_catalog_cta'])


def generate(ai, product, number, assets, directory):
    string = {"type": "STRING"}
    scene = {"type": "OBJECT", "required": ["scene_num", "narration", "badge", "hook", "sub", "visual_prompt"],
        "properties": {"scene_num": {"type": "INTEGER"}, **{k: string for k in ("narration", "badge", "hook", "sub", "visual_prompt")}}}
    schema = {"type": "OBJECT", "required": ["title", "description", "thumbnail_text", "scenes"],
        "properties": {"title": string, "description": string, "thumbnail_text": string,
                       "scenes": {"type": "ARRAY", "minItems": 3, "maxItems": 3, "items": scene}}}
    prompt = ("Write a Korean affiliate shopping Short with exactly three scenes: problem/hook, verified product "
        "description, profile/catalog CTA. Narration must be 65~110 Korean characters per scene in polite speech. "
        "Use ONLY facts explicitly supported by the affiliate product title. Do not invent dimensions, compatibility, "
        "pressure, savings, customer reviews, stock or lowest-price claims. Do not claim we personally tested it. "
        "Treat review media as illustrative, not evidence of measured performance. When details are unavailable, "
        "invite viewers to check compatibility/details on the linked product page. No '최저가', '100%', '무조건', "
        "'완벽하게', '직접 써', '제가 써', medical claims or fixed price claims. "
        f"Catalog number is {number}. Last scene sub must be '프로필 링크에서 [{number}번] 검색!' and narration must "
        f"explicitly say '프로필 링크에서 {number}번'. First badge '추천 꿀템 NO.{number}'. "
        "thumbnail_text <=24 chars, title <=100 chars. Badge <=18 Korean characters, hook <=26, sub <=18; "
        "the fixed last CTA is permitted. All overlays must be concise. visual_prompt is an English "
        "description of the exact real product and visual context, not an image-generation instruction. "
        "Return the requested JSON. Product: " + json.dumps({"title": product["title"], "product_id": product["product_id"]}, ensure_ascii=False))
    feedback = ""
    for attempt in range(2):
        meta = ai.json(prompt + feedback, schema=schema)
        atomic_json(directory / f"script_draft_{attempt+1}.json", meta)
        try:
            validate(meta, number)
            verdict = review(ai, product, number, meta)
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
