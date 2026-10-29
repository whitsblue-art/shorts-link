import os
import json
import random

def run_automation():
    print("🤖 스마트세이버 자동화 로봇이 실행되었습니다!")
    
    # 1. 기존 products.json 불러오기
    json_file = 'products.json'
    if os.path.exists(json_file):
        with open(json_file, 'r', encoding='utf-8') as f:
            products = json.load(f)
    else:
        products = []

    # 2. 새로운 상품 번호 및 데이터 생성 (A/B 테스트 하이브리드 로직)
    new_id = len(products) + 1
    
    # 예시 신규 상품 데이터 (실제 구동 시 쿠팡/샤오홍슈 API 결과로 대체됨)
    sample_items = [
        {"title": "순간 흡수 규조흙 발매트 꿀템", "url": "https://link.coupang.com/a/example2"},
        {"title": "자석 밀대 창문 청소기", "url": "https://link.coupang.com/a/example3"},
        {"title": "씽크대 거름망 자동 압축기", "url": "https://link.coupang.com/a/example4"}
    ]
    
    selected_item = random.choice(sample_items)
    
    new_product = {
        "id": new_id,
        "title": selected_item["title"],
        "thumbnail": "https://via.placeholder.com/150",
        "coupang_url": selected_item["url"]
    }

    # 3. products.json 맨 앞에 새 상품 추가 (인포크링크 페이지 실시간 반영)
    products.insert(0, new_product)

    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=4)
        
    print(f"✨ [NO.{new_id}] '{selected_item['title']}' 상품이 인포크링크 카탈로그에 자동 등록되었습니다!")

if __name__ == "__main__":
    run_automation()
