import os
import json
import urllib.request
import google.generativeai as genai
from PIL import Image

PRODUCTS_FILE = 'products.json'

api_key = os.environ.get("GEMINI_API_KEY", "")
if not api_key:
    raise RuntimeError("❌ GEMINI_API_KEY가 설정되지 않았습니다! GitHub Secrets를 확인하세요.")
genai.configure(api_key=api_key)

def verify_image_with_gemini(img_path, product_keyword):
    model = genai.GenerativeModel('gemini-1.5-flash')
    img = Image.open(img_path)
    prompt = (
        f"이 이미지에 '{product_keyword}'(주방 싱크대 수전/수도꼭지)가 명확하게 보입니까?\n"
        "변기나 샤워부스만 있는 일반 욕실 전체 인테리어 사진이면 무조건 FALSE라고 답하세요.\n"
        "반드시 TRUE 또는 FALSE 한 단어로만 답하세요."
    )
    response = model.generate_content([img, prompt])
    result = response.text.strip().upper()
    print(f"   👉 [Gemini 비전 판독 응답]: {result}")
    return "TRUE" in result and "FALSE" not in result

def verify_and_process():
    print("🤖 [1단계] 후보 이미지 Gemini 비전 AI 실제 엄격 검수 시작...")
    
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            try: products = json.load(f)
            except: products = []
    else:
        products = []

    next_id = max([p.get("id", 0) for p in products], default=0) + 1
    product_title = "물 튀김 방지 360도 회전 코브라 수전 헤드"

    # 일부러 1번에 문제의 '욕실/변기' 사진을 배치 -> AI가 실제로 FALSE로 걸러내는지 검증
    candidate_images = [
        ("문제의 욕실/변기 사진 (탈락 테스트용)", "https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=800&q=80"),
        ("주방 싱크대 수전 사진 1", "https://images.unsplash.com/photo-1585704032915-c3400ca199e7?w=800&q=80"),
        ("주방 싱크대 수전 사진 2", "https://images.unsplash.com/photo-1556911220-e15b29be8c8f?w=800&q=80"),
        ("주방 싱크대 수전 사진 3", "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=800&q=80")
    ]

    verified_urls = []
    req_headers = {'User-Agent': 'Mozilla/5.0'}

    for label, url in candidate_images:
        print(f"🔍 검수 중: {label}")
        temp_img = "temp_verify.jpg"
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req) as resp, open(temp_img, 'wb') as out:
            out.write(resp.read())
        
        is_valid = verify_image_with_gemini(temp_img, "주방 싱크대 수전 수도꼭지")
        if os.path.exists(temp_img):
            os.remove(temp_img)

        if is_valid:
            print(f"   ✅ [검수 통과]: {label}")
            verified_urls.append(url)
        else:
            print(f"   ❌ [검수 반려 - 즉시 폐기]: {label}")

        if len(verified_urls) == 3:
            break

    if not verified_urls:
        raise RuntimeError("❌ 검수를 통과한 이미지가 하나도 없어 파이프라인을 중단합니다.")

    while len(verified_urls) < 3:
        verified_urls.append(verified_urls[-1])

    new_prod = {
        "id": next_id,
        "title": product_title,
        "link": "https://www.coupang.com/np/search?q=코브라+수전+헤드",
        "verified": True,
        "scenes": [
            {
                "image": verified_urls[0],
                "badge": f"추천 꿀템 NO.{next_id}",
                "hook": "설거지할 때마다 물 튀김?",
                "sub": "사방으로 튀는 물 한 방에 해결!",
                "tts": f"설거지할 때마다 사방으로 튀는 물, 스트레스받으시죠? {product_title}로 해결하세요!"
            },
            {
                "image": verified_urls[1],
                "badge": "360도 자유자재 회전",
                "hook": "강력 수압 & 각도 조절",
                "sub": "싱크대 구석구석 빈틈없이 세척",
                "tts": "원하는 각도로 부드럽게 꺾이며, 강력한 수압으로 싱크대 구석구석을 깨끗하게 씻어냅니다."
            },
            {
                "image": verified_urls[2],
                "badge": "프로필 링크 클릭",
                "hook": "어디서 살 수 있을까?",
                "sub": f"프로필 링크에서 [{next_id}번] 검색!",
                "tts": f"지금 바로 프로필 링크에서 {next_id}번을 검색해 최저가로 만나보세요!"
            }
        ]
    }
    
    products.insert(0, new_prod)
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    
    print(f"🎉 [1단계 완료] 불량 이미지 폐기 및 진짜 수전 이미지 3장 저장 완료!")

if __name__ == "__main__":
    verify_and_process()
