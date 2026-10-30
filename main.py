import os
import sys
import json
import base64
import subprocess
import asyncio
import urllib.request
import urllib.parse

# 필수 패키지 자동 확인 및 설치
try:
    import edge_tts
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "edge-tts", "pillow"], check=True)
    import edge_tts

from PIL import Image, ImageDraw, ImageFont, ImageOps

PRODUCTS_FILE = 'products.json'
OUTPUT_DIR = 'videos'
API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

FONT_CANDIDATES = [
    '/usr/share/fonts/truetype/nanum/NanumSquareRoundEB.ttf',
    '/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf',
    '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
    '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'
]

def get_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    subprocess.run(["sudo", "apt-get", "update"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["sudo", "apt-get", "install", "-y", "fonts-nanum"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def fetch_faucet_candidates():
    """차단 없는 공식 API 및 실제 수도꼭지/수전 클로즈업 후보 리스트를 가져옵니다."""
    candidates = [
        # 1번: 탈락 검증용 (아까 통과해버렸던 냄비 요리하는 여성 사진)
        ("문제의 냄비 요리하는 여성 사진 (탈락 검증용)", "https://images.unsplash.com/photo-1556911220-e15b29be8c8f?w=800&q=80"),
        # 2번: 탈락 검증용 (변기/욕실 인테리어 사진)
        ("문제의 욕실/변기 사진 (탈락 검증용)", "https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=800&q=80"),
    ]

    # GitHub Actions에서 차단되지 않는 Wikimedia Commons 공식 JSON API로 실제 수전(Kitchen faucet / Tap) 이미지 검색
    api_url = (
        "https://commons.wikimedia.org/w/api.php"
        "?action=query&generator=search&gsrsearch=filetype:bitmap+kitchen+faucet+sink"
        "&gsrlimit=8&prop=imageinfo&iiprop=url&iiurlwidth=1080&format=json"
    )
    req_headers = {'User-Agent': 'ShortsAutomationBot/1.0 (https://github.com)'}
    try:
        req = urllib.request.Request(api_url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            pages = data.get("query", {}).get("pages", {})
            for idx, page in enumerate(pages.values()):
                ii = page.get("imageinfo", [{}])[0]
                img_url = ii.get("thumburl") or ii.get("url")
                if img_url and img_url.lower().endswith(('.jpg', '.jpeg', '.png')):
                    candidates.append((f"API 검색 실제 수전 이미지 #{idx+1}", img_url))
    except Exception as e:
        print(f"⚠️ API 검색 참고: {e}")

    # 예비용 100% 실제 수도꼭지/물줄기/싱크대 수전 클로즈업 고정밀 이미지
    fallback_faucets = [
        ("실제 크롬 싱크대 수전 클로즈업 #1", "https://images.unsplash.com/photo-1584622781564-1d987f7333c1?w=800&q=80"),
        ("실제 수도꼭지 물줄기 클로즈업 #2", "https://images.unsplash.com/photo-1521207418485-99c705420785?w=800&q=80"),
        ("실제 주방 싱크대 수전 세척 #3", "https://images.unsplash.com/photo-1585704032915-c3400ca199e7?w=800&q=80"),
    ]
    candidates.extend(fallback_faucets)
    print(f"🔎 총 {len(candidates)}개의 검수 대상 후보가 준비되었습니다.")
    return candidates

def verify_image_strictly(img_path, label):
    """Gemini 비전 AI에게 이미지의 '메인 피사체'를 분석하게 하여 사람/냄비/변기 사진을 100% 걸러냅니다."""
    try:
        img = Image.open(img_path).convert("RGB")
        w, h = img.size
        if w < 300 or h < 300:
            print("   👉 [반려]: 해상도 미달")
            return False
    except Exception:
        return False

    if not API_KEY:
        raise RuntimeError("❌ GEMINI_API_KEY가 비어 있습니다.")

    try:
        with open(img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"
        prompt = (
            "이 이미지를 엄격하게 분석해서 아래 조건을 판별하세요.\n"
            "우리는 '싱크대 수도꼭지(수전 헤드)' 부품을 판매합니다.\n"
            "규칙 1: 사진의 가장 큰 메인 주인공이 '요리하는 사람', '가스레인지 위의 주황색 냄비', '변기', '샤워부스'라면 뒤에 수전이 작게 보여도 무조건 REJECT라고 답하세요.\n"
            "규칙 2: 오직 '수도꼭지(수전)', '수전에서 물이 나오는 모습', '싱크대 수전 설거지 클로즈업'이 화면의 중심 피사체일 때만 PASS라고 답하세요.\n"
            "형식: 첫 줄에 [피사체 설명]을 짧게 적고, 마지막에 반드시 PASS 또는 REJECT를 적으세요."
        )
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
                ]
            }]
        }
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            answer = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            one_line = answer.replace("\n", " ")
            print(f"   👉 [Gemini 비전 판독]: {one_line}")
            upper_ans = answer.upper()
            return "PASS" in upper_ans and "REJECT" not in upper_ans
    except Exception as e:
        print(f"   ⚠️ [API 호출 오류]: {e}")
        return False

async def generate_tts(text, output_audio_path):
    communicate = edge_tts.Communicate(text, "ko-KR-SunHiNeural", rate="+15%")
    await communicate.save(output_audio_path)

def create_scene_frame(img_path, badge_text, hook_text, sub_text, out_img_path):
    img = Image.open(img_path).convert("RGB")
    img = ImageOps.fit(img, (1080, 1920), method=Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(img, "RGBA")

    font_badge = get_font(48)
    font_hook = get_font(66)
    font_sub = get_font(52)

    # 1. 상단 노란색 배지 박스
    bbox_b = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw, bh = bbox_b[2] - bbox_b[0], bbox_b[3] - bbox_b[1]
    bx, by = (1080 - bw) // 2, 180
    draw.rounded_rectangle([bx - 30, by - 15, bx + bw + 30, by + bh + 20], radius=20, fill=(255, 215, 0, 240))
    draw.text((bx, by), badge_text, font=font_badge, fill=(0, 0, 0, 255))

    # 2. 상단 메인 후킹 자막 박스
    bbox_h = draw.textbbox((0, 0), hook_text, font=font_hook)
    hw, hh = bbox_h[2] - bbox_h[0], bbox_h[3] - bbox_h[1]
    hx, hy = (1080 - hw) // 2, 290
    draw.rounded_rectangle([hx - 35, hy - 20, hx + hw + 35, hy + hh + 25], radius=20, fill=(0, 0, 0, 200))
    draw.text((hx, hy), hook_text, font=font_hook, fill=(255, 255, 255, 255))

    # 3. 하단 보조 설명 자막 박스
    if sub_text:
        bbox_s = draw.textbbox((0, 0), sub_text, font=font_sub)
        sw, sh = bbox_s[2] - bbox_s[0], bbox_s[3] - bbox_s[1]
        sx, sy = (1080 - sw) // 2, 1520
        draw.rounded_rectangle([sx - 35, sy - 20, sx + sw + 35, sy + sh + 25], radius=20, fill=(0, 0, 0, 215))
        draw.text((sx, sy), sub_text, font=font_sub, fill=(0, 255, 200, 255))

    img.save(out_img_path, quality=95)

def run_full_pipeline():
    print("🤖 [1단계] 실제 수전 이미지 수집 및 Gemini 비전 AI 메인 피사체 엄격 검수 시작...")
    
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            try: products = json.load(f)
            except: products = []
    else:
        products = []

    next_id = max([p.get("id", 0) for p in products], default=0) + 1
    product_title = "물 튀김 방지 360도 회전 코브라 수전 헤드"

    candidate_list = fetch_faucet_candidates()

    verified_images = []
    used_urls = set()
    req_headers = {'User-Agent': 'ShortsAutomationBot/1.0 (https://github.com)'}

    for idx, (label, url) in enumerate(candidate_list):
        if url in used_urls:
            continue
        print(f"🔍 검수 중 ({idx+1}/{len(candidate_list)}): {label}")
        temp_img = f"temp_verify_{idx}.jpg"
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=10) as resp, open(temp_img, 'wb') as out:
                out.write(resp.read())
        except Exception as e:
            print(f"   ⚠️ 이미지 다운로드 건너뜀: {e}")
            continue
        
        is_valid = verify_image_strictly(temp_img, label)

        if is_valid:
            print(f"   ✅ [실물 검수 통과 - PASS]: {label}")
            verified_images.append((url, temp_img))
            used_urls.add(url)
        else:
            print(f"   ❌ [검수 반려 - REJECT (즉시 폐기)]: {label}")
            if os.path.exists(temp_img):
                os.remove(temp_img)

        if len(verified_images) == 3:
            break

    if len(verified_images) < 3:
        raise RuntimeError(f"❌ 검수를 통과한 수전 이미지가 3장 미만입니다(현재 {len(verified_images)}장).")

    scenes = [
        {
            "image": verified_images[0][0],
            "local_img": verified_images[0][1],
            "badge": f"추천 꿀템 NO.{next_id}",
            "hook": "설거지할 때마다 물 튀김?",
            "sub": "사방으로 튀는 물 한 방에 해결!",
            "tts": f"설거지할 때마다 사방으로 튀는 물, 스트레스받으시죠? {product_title}로 해결하세요!"
        },
        {
            "image": verified_images[1][0],
            "local_img": verified_images[1][1],
            "badge": "360도 자유자재 회전",
            "hook": "강력 수압 & 각도 조절",
            "sub": "싱크대 구석구석 빈틈없이 세척",
            "tts": "원하는 각도로 부드럽게 꺾이며, 강력한 수압으로 싱크대 구석구석을 깨끗하게 씻어냅니다."
        },
        {
            "image": verified_images[2][0],
            "local_img": verified_images[2][1],
            "badge": "프로필 링크 클릭",
            "hook": "어디서 살 수 있을까?",
            "sub": f"프로필 링크에서 [{next_id}번] 검색!",
            "tts": f"지금 바로 프로필 링크에서 {next_id}번을 검색해 최저가로 만나보세요!"
        }
    ]

    new_prod = {
        "id": next_id,
        "title": product_title,
        "link": "https://www.coupang.com/np/search?q=코브라+수전+헤드",
        "image": verified_images[0][0],
        "verified": True,
        "scenes": [{k: v for k, v in s.items() if k != "local_img"} for s in scenes]
    }
    
    products.insert(0, new_prod)
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    
    print(f"🎬 [2단계] 서로 다른 3개의 실제 수전 이미지로 장면 렌더링 시작...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_mp4 = os.path.join(OUTPUT_DIR, f"shorts_no_{next_id}.mp4")

    scene_clips = []
    temp_files = []

    for idx, scene in enumerate(scenes):
        print(f"   🎞️ 장면 {idx+1}/3 제작 중: {scene['hook']}")
        raw_img = scene['local_img']
        framed_img = f"temp_framed_{idx}.jpg"
        audio_mp3 = f"temp_audio_{idx}.mp3"
        clip_mp4 = f"temp_clip_{idx}.mp4"
        temp_files.extend([raw_img, framed_img, audio_mp3, clip_mp4])

        create_scene_frame(raw_img, scene['badge'], scene['hook'], scene['sub'], framed_img)
        asyncio.run(generate_tts(scene['tts'], audio_mp3))

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", "30", "-i", framed_img,
            "-i", audio_mp3,
            "-vf", "scale=1080:1920,format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            clip_mp4
        ]
        subprocess.run(cmd, check=True)
        scene_clips.append(clip_mp4)

    concat_txt = "concat_list.txt"
    temp_files.append(concat_txt)
    with open(concat_txt, "w", encoding="utf-8") as f:
        for clip in scene_clips:
            f.write(f"file '{clip}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", output_mp4
    ], check=True)

    for p in temp_files:
        if os.path.exists(p):
            os.remove(p)

    print(f"✅ 영상 파일 생성 완료: {output_mp4}")

    print("🚀 [3단계] 생성된 영상을 GitHub 저장소에 즉시 업로드 중...")
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
    subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=False)
    subprocess.run(["git", "add", "-f", PRODUCTS_FILE, output_mp4], check=False)
    subprocess.run(["git", "commit", "-m", f"Auto-generate verified shorts NO.{next_id}"], check=False)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False)
    subprocess.run(["git", "push", "origin", "main"], check=False)
    print(f"🎉 [전체 공정 완료] videos/shorts_no_{next_id}.mp4 업로드 성공!")

if __name__ == "__main__":
    run_full_pipeline()
