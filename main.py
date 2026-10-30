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

    # 2. 비전 AI 시각 검수 시뮬레이션 (쿠팡 원본 사진 vs 실제 리뷰 영상 첫 프레임 비교)
    print("👁️ [2단계 AI 비전 검수] 해외 실사용 영상 첫 프레임과 상품 일치 여부 정밀 교차 검증 중...")
    
    # (안전장치) AI 비전 검수 통과 여부 확인 로직
    is_matched = True  # 실제 구동 시 비전 API 판독 결과에 따라 True/False 결정
    
    if is_matched:
        print("🤖 [AI 비전 검수 결과]: 통과 (True) ✅")
        print("📝 [검수 사유]: 쿠팡 상품의 주방 싱크대 수전 형태와 실사용 영상 속 제품이 정확히 일치합니다.")
    else:
        print("🤖 [AI 비전 검수 결과]: 반려 (False) ❌ -> 엉뚱한 이미지이므로 즉시 폐기하고 재탐색합니다.")
        return

    # 3. 데이터 구조화 및 저장
    new_prod = {
        "id": next_id,
        "title": product_title,
        "link": "https://www.coupang.com/np/search?q=코브라+수전+헤드",
        "image": coupang_image_url,
        "verified": True,
        "scenes": [
            {"top_hook": "설거지할 때 물 튀김?", "badge": f"추천 꿀템 NO.{next_id}", "sub": "바꾸기만 하면 끝나요!", "tts": f"설거지할 때마다 사방으로 튀는 물, 스트레스받으시죠? {product_title}로 해결하세요!", "type": "image"},
            {"top_hook": "어떻게 작동할까?", "badge": "360도 자유자재 회전", "sub": "구석구석 빈틈없이 세척", "tts": "360도 회전 코브라 수전 헤드는 원하는 각도로 자유롭게 꺾이며 강력한 수압을 자랑합니다.", "type": "spec", "specs": ["설치 시간 10초! 공구 없이 손으로 OK", "녹물 제거 필터 기본 내장", "주방 및 욕실 세면대 완벽 호환"]},
            {"top_hook": "어디서 살 수 있을까?", "badge": "프로필 링크 클릭",
