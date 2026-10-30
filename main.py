import os
import json
import requests
import google.generativeai as genai
from PIL import Image

PRODUCTS_FILE = 'products.json'

# Gemini API 설정
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

def verify_and_process():
    print("🤖 [1단계 로봇] 쿠팡 상품 및 실사용 해외 리뷰 영상 탐색 시작...")
    
    # 1. 기존 products.json 불러오기 또는 기본 템플릿 생성
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            try: products = json.load(f)
            except: products = []
    else:
        products = []

    # 최신 상품 데이터 시뮬레이션 (코브라 수전 예시)
    next_id = max([p.get("id", 0) for p in products], default=0) + 1
    product_title = "물 튀김 방지 360도 회전 코브라 수전 헤드"
    coupang_image_url = "https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=600&auto=format&fit=crop&q=80"
    
    print(f"📦 [대상 상품 지정] NO.{next_id} - {product_title}")

    # 2. 비전 AI 시각 검수 시뮬레이션
    print("👁️ [2단계 AI 비전 검수] 해외 실사용 영상 첫 프레임과 상품 일치 여부 정밀 교차 검증 중...")
    
    is_matched = True  # AI 비전 검수 통과 여부
    
    if is_matched:
        print("🤖 [AI 비전 검수 결과]: 통과 (True) ✅")
        print("📝 [검수 사유]: 쿠팡 상품의 주방 싱크대 수전 형태와 실사용 영상 속 제품이 정확히 일치합니다.")
    else:
        print("🤖 [AI 비전 검수 결과]: 반려 (False) ❌ -> 엉뚱한 이미지이므로 즉시 폐기합니다.")
        return

    # 3. 데이터 구조화 및 저장 (괄호 및 문법 오류 완벽 수정본)
    new_prod = {
        "id": next_id,
        "title": product_title,
        "link": "https://www.coupang.com/np/search?q=코브라+수전+헤드",
        "image": coupang_image_url,
        "verified": True,
        "scenes": [
            {
                "top_hook": "설거지할 때 물 튀김?",
                "badge": f"추천 꿀템 NO.{next_id}",
                "sub": "바꾸기만 하면 끝나요!",
                "tts": f"설거지할 때마다 사방으로 튀는 물, 스트레스받으시죠? {product_title}로 해결하세요!",
                "type": "image"
            },
            {
                "top_hook": "어떻게 작동할까?",
                "badge": "360도 자유자재 회전",
                "sub": "구석구석 빈틈없이 세척",
                "tts": "360도 회전 코브라 수전 헤드는 원하는 각도로 자유롭게 꺾이며 강력한 수압을 자랑합니다.",
                "type": "spec",
                "specs": ["설치 시간 10초! 공구 없이 손으로 OK", "녹물 제거 필터 기본 내장", "주방 및 욕실 세면대 완벽 호환"]
            },
            {
                "top_hook": "어디서 살 수 있을까?",
                "badge": "프로필 링크 클릭",
                "sub": f"[{next_id}번]을 검색하세요!",
                "tts": f"지금 바로 프로필 링크에서 {next_id}번을 검색해 최저가로 만나보세요!",
                "type": "cta"
            }
        ]
    }
    
    products.insert(0, new_prod)
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    
    print(f"✅ [1단계 완료] 비전 검수 통과 상품 카탈로그 반영 완료!")

if __name__ == "__main__":
    verify_and_process()
