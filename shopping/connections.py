"""Read-only setup report. No catalog writes, video generation or YouTube uploads."""
import json
import os
from pathlib import Path
import sys

import requests

from .core import GateError, ROOT, atomic_json
from .coupang import Coupang
from .channel import public_channel


def main():
    results = []
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        try:
            response = requests.get("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash",
                                    headers={"x-goog-api-key": key}, timeout=(15, 30))
            results.append({"check": "Gemini API", "ok": response.status_code == 200,
                            "detail": f"HTTP {response.status_code}"})
            if response.status_code == 200:
                generated = requests.post('https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent',
                    headers={"x-goog-api-key": key}, json={"contents":[{"parts":[{"text":"Reply with OK only."}]}],
                        "generationConfig":{"maxOutputTokens":32,"thinkingConfig":{"thinkingBudget":0}}}, timeout=(15,45))
                detail = f"Tiny generation request HTTP {generated.status_code}; image/audio QA is separate"
                if generated.status_code == 429:
                    message = str(generated.json().get('error',{}).get('message','')).lower()
                    detail = "Project monthly spending cap reached" if 'spending cap' in message else "Generation rate/quota limit reached"
                results.append({"check":"Gemini generation capability","ok":generated.status_code == 200,"detail":detail})
        except requests.RequestException:
            results.append({"check": "Gemini API", "ok": False, "detail": "Network failure"})
    else:
        results.append({"check": "Gemini API", "ok": False, "detail": "GEMINI_API_KEY secret missing"})
    try:
        api = Coupang()
        product = api.search("코브라 수전 헤드", limit=1)[0]
        api.deeplink(product)
        results.append({"check": "Coupang affiliate API", "ok": True, "detail": "Product search and exact deeplink passed"})
    except GateError as exc:
        results.append({"check": "Coupang affiliate API", "ok": False, "detail": str(exc)})
    shopping_token = os.getenv("SHOPPING_YOUTUBE_TOKEN_JSON", "").strip()
    config = json.loads((ROOT / "shopping_config.json").read_text(encoding="utf-8"))
    target = os.getenv("SHOPPING_CHANNEL_URL", "").strip() or config.get("shopping_channel_url", "")
    try:
        identity = public_channel(target)
        expected = config.get("shopping_channel_name")
        if expected and identity["title"] != expected:
            raise GateError("Public channel name does not match the configured shopping channel")
        if config.get("shopping_channel_id") and identity["channel_id"] != config["shopping_channel_id"]:
            raise GateError("Public channel ID differs from the verified shopping destination")
        results.append({"check": "Public shopping channel", "ok": True, "detail": identity})
    except (GateError, ValueError) as exc:
        results.append({"check": "Public shopping channel", "ok": False, "detail": str(exc)})
    if shopping_token:
        try:
            from .check_channel import main as check_channel
            check_channel()
            results.append({"check": "Shopping channel authorization", "ok": True, "detail": "OAuth channel matches the intended destination"})
        except GateError as exc:
            results.append({"check": "Shopping channel authorization", "ok": False, "detail": str(exc)})
        except Exception:
            results.append({"check": "Shopping channel authorization", "ok": False, "detail": "OAuth/target verification failed; no credentials logged"})
    else:
        results.append({"check": "Shopping channel authorization", "ok": False,
            "detail": "SHOPPING_YOUTUBE_TOKEN_JSON secret missing"})
    output = ROOT / "current_episode"
    atomic_json(output / "connection_report.json", results)
    lines = ["## 쇼핑 자동화 연결 검사", "", "영상 생성·카탈로그 변경·유튜브 업로드를 하지 않는 검사입니다.", ""]
    for result in results:
        lines.append(f"- {'PASS' if result['ok'] else 'SETUP REQUIRED'} · {result['check']} · {result['detail']}")
    text = "\n".join(lines) + "\n"
    print(text)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(text, encoding="utf-8")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
