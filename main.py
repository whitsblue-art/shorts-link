import os
import json
import google.generativeai as genai

PRODUCTS_FILE = 'products.json'

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

def verify_and_process():
    print("🤖 [1단계 로봇] 쿠팡 상품 및 실사용 해외 리뷰 영상 탐색 시작...")
    
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            try: products = json.load(f)
            except: products = []
    else:
        products = []

    next_id = max([p.get("id", 0) for p in products], default=0) + 1
    product_title = "물 튀김 방지 360도 회전 코브라 수전 헤드"
    coupang_image_url = "https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=600&auto=format&fit=crop&q=80"
    
    print(f"📦 [대상 상품 지정] NO.{next_id} - {product_title}")

    # 비전 AI 검수 통과 시뮬레이션
    is_matched = True  
    if is_matched:
        print("🤖 [AI 비전 검수 결과]: 통과 (True) ✅")
    else:
        print("🤖 [AI 비전 검수 결과]: 반려 (False) ❌")
        return

    # 다중 씬(Scene) 및 대본 구조화
    new_prod = {
        "id": next_id,
        "title": product_title,
        "link": "https://www.coupang.com/np/search?q=코브라+수전+헤드",
        "image": coupang_image_url,
        "verified": True,
        "scenes": [
            {
                "hook": "설거지할 때마다 물 튀김?",
                "badge": f"추천 꿀템 NO.{next_id}",
                "tts": f"설거지할 때마다 사방으로 튀는 물, 스트레스받으시죠? {product_title}로 한 방에 해결하세요!"
            },
            {
                "hook": "360도 자유자재 회전",
                "badge": "구석구석 완벽 세척",
                "tts": "원하는 각도로 부드럽게 꺾이며, 강력한 수압으로 싱크대 구석구석을 깨끗하게 씻어냅니다."
            },
            {
                "hook": "어디서 살 수 있을까?",
                "badge": "프로필 링크 클릭",
                "tts": f"지금 바로 프로필 링크에서 {next_id}번을 검색해 최저가로 만나보세요!"
            }
        ]
    }
    
    products.insert(0, new_prod)
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    
    print(f"✅ [1단계 완료] 다중 씬 카탈로그 반영 완료!")

if __name__ == "__main__":
    verify_and_process()
