import json
import os
import asyncio
import requests
import subprocess
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageOps

PRODUCTS_FILE = 'products.json'
OUTPUT_DIR = 'videos'
FONT_BOLD = '/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf'
FONT_FALLBACK = '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf'
VOICE = "ko-KR-SunHiNeural"  # 또렷하고 자연스러운 한국어 여성 AI 음성
SPEECH_RATE = "+28%"         # 쇼츠 특유의 빠르고 경쾌한 말 속도

def get_font(size):
    for path in [FONT_BOLD, FONT_FALLBACK]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def wrap_text(text, max_chars=16):
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

async def generate_tts(text, out_path):
    communicate = edge_tts.Communicate(text, VOICE, rate=SPEECH_RATE)
    await communicate.save(out_path)

def get_audio_duration(audio_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return max(float(res.stdout.strip()), 1.5)
    except Exception:
        return 2.5

def draw_scene_frame(scene, prod_img, p_id, title, out_img_path):
    # 배경: 고급스러운 다크 그라데이션 톤 (1080x1920)
    canvas = Image.new("RGB", (1080, 1920), (20, 22, 28))
    draw = ImageDraw.Draw(canvas)

    f_hook = get_font(68)
    f_badge = get_font(44)
    f_sub = get_font(76)
    f_card_title = get_font(52)
    f_card_body = get_font(42)

    # 1. 상단 노란색 질문 훅 타이틀 (2번 영상 스타일)
    top_hook = scene.get("top_hook", "오늘의 추천 꿀템!")
    draw.text(
        (540, 230), top_hook, font=f_hook, fill=(255, 225, 60),
        anchor="mm", stroke_width=6, stroke_fill=(0, 0, 0)
    )

    # 2. 중앙 라운드 카드 영역 (Y: 360 ~ 1220)
    card_box = [70, 360, 1010, 1220]
    scene_type = scene.get("type", "image")

    if scene_type == "image":
        # 흰색 라운드 카드 안에 상품 이미지 배치
        draw.rounded_rectangle(card_box, radius=45, fill=(255, 255, 255))
        resized = ImageOps.fit(prod_img, (860, 780), Image.Resampling.LANCZOS)
        canvas.paste(resized, (110, 400))

    elif scene_type == "spec":
        # 스펙 요약 카드
        draw.rounded_rectangle(card_box, radius=45, fill=(245, 247, 252))
        thumb = ImageOps.fit(prod_img, (320, 320), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (380, 400))
        draw.text((540, 770), wrap_text(title, 18), font=f_card_title, fill=(20, 20, 20), anchor="mm", align="center")
        y_pos = 880
        for sp in scene.get("specs", []):
            draw.rounded_rectangle([120, y_pos, 960, y_pos + 80], radius=20, fill=(30, 35, 45))
            draw.text((540, y_pos + 40), f"✔ {sp}", font=get_font(36), fill=(255, 255, 255), anchor="mm")
            y_pos += 100

    elif scene_type == "checklist":
        # 2번 영상의 '이런 분께 맞아요' 다크 체크리스트 박스 완벽 재현
        draw.rounded_rectangle(card_box, radius=45, fill=(12, 14, 18), outline=(70, 75, 90), width=4)
        draw.text((540, 460), "이런 분께 맞아요", font=get_font(62), fill=(255, 255, 255), anchor="mm")
        y_pos = 590
        for chk in scene.get("checks", []):
            # 노란색 동그라미 체크 아이콘
            draw.ellipse([130, y_pos - 28, 190, y_pos + 32], fill=(255, 205, 0))
            draw.text((160, y_pos + 2), "V", font=get_font(38), fill=(0, 0, 0), anchor="mm")
            draw.text((220, y_pos), chk, font=f_card_body, fill=(240, 240, 240), anchor="lm")
            y_pos += 130

        # 하단 미니 스펙 알약
        draw.rounded_rectangle([130, 1020, 950, 1130], radius=25, fill=(35, 38, 48))
        draw.text((540, 1075), f"추천 꿀템 NO.{p_id} · 당일 출고 · 최저가 보장", font=get_font(36), fill=(200, 205, 220), anchor="mm")

    elif scene_type == "cta":
        # 마지막 구매 유도 카드
        draw.rounded_rectangle(card_box, radius=45, fill=(255, 255, 255))
        thumb = ImageOps.fit(prod_img, (500, 500), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (290, 400))
        draw.rounded_rectangle([200, 950, 880, 1060], radius=30, fill=(255, 200, 0))
        draw.text((540, 1005), f"상품 번호 [ {p_id}번 ]", font=get_font(54), fill=(0, 0, 0), anchor="mm")
        draw.text((540, 1135), wrap_text(title, 18), font=get_font(44), fill=(30, 30, 30), anchor="mm")

    # 3. 하단 노란색 알약 배지 (2번 영상 스타일)
    badge_text = scene.get("badge", f"추천 꿀템 NO. {p_id}")
    badge_w = max(len(badge_text) * 42 + 80, 460)
    draw.rounded_rectangle(
        [540 - badge_w // 2, 1310, 540 + badge_w // 2, 1405],
        radius=45, fill=(255, 205, 0)
    )
    draw.text((540, 1357), badge_text, font=f_badge, fill=(15, 15, 15), anchor="mm")

    # 4. 하단 메인 굵은 자막 (검은색 외곽선 강조)
    sub_text = wrap_text(scene.get("sub", title), max_chars=13)
    draw.multiline_text(
        (540, 1530), sub_text, font=f_sub, fill=(255, 255, 255),
        anchor="mm", align="center", spacing=20, stroke_width=8, stroke_fill=(0, 0, 0)
    )

    canvas.save(out_img_path, quality=95)

def make_video():
    if not os.path.exists(PRODUCTS_FILE):
        print("❌ products.json 파일이 없습니다.")
        return

    with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
        products = json.load(f)

    if not products:
        return

    latest = products[0]
    p_id = latest.get('id', 1)
    title = latest.get('title', '추천 꿀템')
    img_url = latest.get('image', '')
    scenes = latest.get('scenes', [])

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_mp4 = os.path.join(OUTPUT_DIR, f"shorts_no_{p_id}.mp4")

    # 상품 이미지 다운로드
    img_path = "temp_prod.jpg"
    try:
        res = requests.get(img_url, timeout=10)
        with open(img_path, 'wb') as f:
            f.write(res.content)
        prod_img = Image.open(img_path).convert("RGB")
    except Exception:
        prod_img = Image.new("RGB", (800, 800), (200, 200, 200))

    segment_files = []
    temp_files = [img_path]

    # 각 씬별로 음성 + 이미지 + 살짝 줌인되는 클립 생성
    for idx, scene in enumerate(scenes):
        frame_file = f"scene_{idx}.jpg"
        audio_file = f"scene_{idx}.mp3"
        seg_mp4 = f"segment_{idx}.mp4"
        temp_files.extend([frame_file, audio_file, seg_mp4])

        # 1) 씬 이미지 그리기
        draw_scene_frame(scene, prod_img, p_id, title, frame_file)

        # 2) 고속 신경망 TTS 생성
        tts_text = scene.get("tts", title)
        if idx == len(scenes) - 1:
            tts_text = f"지금 바로 프로필 링크에서 {p_id}번을 검색해 보세요!"
        asyncio.run(generate_tts(tts_text, audio_file))

        # 3) 오디오 길이에 맞춘 다이나믹 클립 렌더링
        dur = get_audio_duration(audio_file)
        frames = int(dur * 30) + 5
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", frame_file,
            "-i", audio_file,
            "-vf", f"zoompan=z='min(zoom+0.0012,1.06)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30",
            "-t", str(dur),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            seg_mp4
        ]
        subprocess.run(cmd, check=True)
        segment_files.append(seg_mp4)

    # 5개 씬 클립을 하나의 쇼츠 영상으로 이어붙이기
    concat_txt = "concat_list.txt"
    temp_files.append(concat_txt)
    with open(concat_txt, "w", encoding="utf-8") as f:
        for seg in segment_files:
            f.write(f"file '{seg}'\n")

    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_txt, "-c", "copy", output_mp4
    ]
    subprocess.run(concat_cmd, check=True)

    # 임시 파일 삭제
    for tf in temp_files:
        if os.path.exists(tf):
            os.remove(tf)

    print(f"🎬 프로급 다중 씬 쇼츠 생성 완료: {output_mp4}")

if __name__ == "__main__":
    make_video()
