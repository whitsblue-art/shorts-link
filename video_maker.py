import json
import os
import requests
import subprocess
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont

PRODUCTS_FILE = 'products.json'
OUTPUT_DIR = 'videos'
FONT_PATH = '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf'

def wrap_text(text, max_chars=13):
    """글자가 화면 밖으로 나가지 않게 단어 단위로 자동 줄바꿈"""
    words = text.split()
    lines, current = [], ""
    for w in words:
        if len(current) + len(w) + 1 <= max_chars:
            current = (current + " " + w).strip()
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)
    return "\n".join(lines)

def make_video():
    if not os.path.exists(PRODUCTS_FILE):
        print("❌ products.json 파일이 없습니다.")
        return

    with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
        products = json.load(f)

    if not products:
        print("❌ 등록된 상품 데이터가 없습니다.")
        return

    # 가장 최근에 추가된(맨 위) 상품 선택
    latest = products[0]
    p_id = latest.get('id', 1)
    title = latest.get('title', '추천 꿀템')
    img_url = latest.get('image', '')

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_mp4 = os.path.join(OUTPUT_DIR, f"shorts_no_{p_id}.mp4")

    # 1. 상품 이미지 다운로드 및 리사이징
    img_path = "temp_product.jpg"
    try:
        res = requests.get(img_url, timeout=10)
        with open(img_path, 'wb') as f:
            f.write(res.content)
        prod_img = Image.open(img_path).convert("RGB")
        prod_img = prod_img.resize((900, 900), Image.Resampling.LANCZOS)
    except Exception as e:
        print("이미지 로드 실패, 기본 배경으로 대체합니다:", e)
        prod_img = Image.new("RGB", (900, 900), (50, 50, 50))

    # 2. 쇼츠 캔버스(1080x1920) 생성 및 디자인 합성
    canvas = Image.new("RGB", (1080, 1920), (18, 18, 18))
    canvas.paste(prod_img, (90, 480))

    draw = ImageDraw.Draw(canvas)
    try:
        font_badge = ImageFont.truetype(FONT_PATH, 55)
        font_title = ImageFont.truetype(FONT_PATH, 70)
        font_cta = ImageFont.truetype(FONT_PATH, 52)
    except Exception:
        font_badge = ImageFont.load_default()
        font_title = ImageFont.load_default()
        font_cta = ImageFont.load_default()

    # 상단 상품 번호 배지
    draw.rounded_rectangle([340, 160, 740, 260], radius=25, fill=(245, 176, 0))
    draw.text((540, 210), f"추천 꿀템 NO. {p_id}", font=font_badge, fill=(18, 18, 18), anchor="mm")

    # 상단 상품명 (자동 줄바꿈)
    wrapped_title = wrap_text(title, max_chars=13)
    draw.multiline_text((540, 360), wrapped_title, font=font_title, fill=(255, 255, 255), anchor="mm", align="center", spacing=18)

    # 하단 프로필 링크 유도 배너
    draw.rounded_rectangle([90, 1480, 990, 1700], radius=30, fill=(38, 38, 38), outline=(245, 176, 0), width=4)
    cta_text = f"프로필 링크에서 [{p_id}번] 검색!\n구매 링크 바로가기 👆"
    draw.multiline_text((540, 1590), cta_text, font=font_cta, fill=(245, 176, 0), anchor="mm", align="center", spacing=22)

    frame_path = "temp_frame.jpg"
    canvas.save(frame_path, quality=95)

    # 3. 한국어 AI 나레이션 음성(TTS) 생성
    narration = f"스마트세이버 오늘의 추천 꿀템, {p_id}번, {title}! 지금 바로 프로필 링크에서 {p_id}번을 검색해 보세요!"
    tts = gTTS(text=narration, lang='ko')
    audio_path = "temp_audio.mp3"
    tts.save(audio_path)

    # 4. FFmpeg으로 부드러운 줌인(Zoom-in) 효과 + 오디오 합성 렌더링
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", frame_path,
        "-i", audio_path,
        "-vf", "zoompan=z='min(zoom+0.0005,1.08)':d=300:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_mp4
    ]
    subprocess.run(cmd, check=True)

    # 임시 파일 정리
    for temp_f in [img_path, frame_path, audio_path]:
        if os.path.exists(temp_f):
            os.remove(temp_f)

    print(f"🎬 쇼츠 영상 생성 완료: {output_mp4}")

if __name__ == "__main__":
    make_video()
