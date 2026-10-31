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
    try:
        from .ai import AI
        ai=AI()
        result=ai.json('Connection check only: return {"ok":true}.',schema={"type":"OBJECT","properties":{"ok":{"type":"BOOLEAN"}}})
        results.append({"check":"OpenAI structured generation","ok":result.get("ok") is True,"detail":"Authenticated Responses API and JSON contract passed; full media QA is separate"})
    except GateError as exc:
        results.append({"check":"OpenAI structured generation","ok":False,"detail":str(exc)})
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
