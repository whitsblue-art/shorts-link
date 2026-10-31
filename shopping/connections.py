"""Read-only setup report. No catalog writes, video generation or YouTube uploads."""
import json
import os
from pathlib import Path
import sys

import requests

from .core import GateError, ROOT, atomic_json
from .coupang import Coupang


def main():
    results = []
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        try:
            response = requests.get("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash",
                                    headers={"x-goog-api-key": key}, timeout=(15, 30))
            results.append({"check": "Gemini API", "ok": response.status_code == 200,
                            "detail": f"HTTP {response.status_code}"})
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
    target = os.getenv("SHOPPING_CHANNEL_URL", "").strip()
    results.append({"check": "Shopping channel configuration", "ok": bool(shopping_token and target),
        "detail": "Shopping token and target set" if shopping_token and target else
                  "Set SHOPPING_YOUTUBE_TOKEN_JSON secret and SHOPPING_CHANNEL_URL variable"})
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
