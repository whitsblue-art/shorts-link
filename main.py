import json
import os

PRODUCTS_FILE = 'products.json'

# 로봇이 순차적으로 꺼내 쓸 자동화 상품 및 실제 고화질 이미지 데이터베이스
AUTO_CATALOG = [
    {
        "title": "물 튀김 방지 360도 회전 코브라 수전 헤드",
        "link": "https://www.coupang.com/np/search?q=코브라+수전+헤드",
        "image": "https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=300&auto=format&fit=crop&q=80"
    },
    {
        "title": "씽크대 거름망 자동 압축기",
        "link": "https://www.coupang.com/np/search?q=싱크대+거름망",
        "image": "https://images.unsplash.com/photo-1556911220-e15b29be8c8f?w=300&auto=format&fit=crop&q=80"
    },
    {
        "title": "자석식 공중부양 무타공 양치컵 홀더 세트",
        "link": "https://www.coupang.com/np/search?q=자석+양치컵",
        "image": "https://images.unsplash.com/photo-1620626011761-996317b8d101?w=300&auto=format&fit=crop&q=80"
    },
    {
        "title": "원터치 실리콘 자동 밀폐 쌀통 10kg",
        "link": "https://www.coupang.com/np/search?q=밀폐+쌀통",
        "image": "https://images.unsplash.com/photo-1586201375761-83865001e31c?w=300&auto=format&fit=crop&q=80"
    },
    {
        "title": "초강력 틈새 먼지제거 정전기 청소포 막대걸레",
        "link": "https://www.coupang.com/np/search?q=틈새+먼지떨이",
        "image": "https://images.unsplash.com/photo-1581578731548-c64695cc6952?w=300&auto=format&fit=crop&q=80"
    },
    {
        "title": "다용도 회전식 주방 양념통 정리대 선반",
        "link": "https://www.coupang.com/np/search?q=회전식+양념통+선반",
        "image": "https://images.unsplash.com/photo-1590794056226-79ef3a8147e1?w=300&auto=format&fit=crop&q=80"
    }
]

def update_catalog():
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            try:
                products = json.load(f)
            except json.JSONDecodeError:
                products = []
    else:
        products = []

    # 1. 기존 상품 중 회색 박스(빈 이미지)로 되어 있는 항목을 실제 사진으로 자동 교체
    for p in products:
        idx = p.get("id", 1) - 1
        if not p.get("image") or "placeholder" in p.get("image", "") or "150" in p.get("image", ""):
            p["image"] = AUTO_CATALOG[idx % len(AUTO_CATALOG)]["image"]

    # 2. 다음 순번 신규 상품 및 이미지 자동 추가
    next_id = max([p.get("id", 0) for p in products], default=0) + 1
    template = AUTO_CATALOG[(next_id - 1) % len(AUTO_CATALOG)]

    new_product = {
        "id": next_id,
        "title": template["title"],
        "link": template["link"],
        "image": template["image"]
    }

    # 최신 번호가 맨 위에 오도록 추가
    products.insert(0, new_product)

    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print(f"✅ [NO.{next_id}] {new_product['title']} (실제 이미지 포함) 자동 업데이트 완료!")

if __name__ == "__main__":
    update_catalog()
