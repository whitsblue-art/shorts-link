import json
import os
import asyncio
import requests
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageOps

PRODUCTS_FILE = 'products.json'
OUTPUT_DIR = 'videos'
FONT_PATHS = [
    '/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf',
    '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
    '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'
]
VOICE = "ko-KR-SunHiNeural"
SPEECH_RATE = "+30%"

def get_font(size):
    for path in FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

def wrap_text(text, max_chars=15):
    words = str(text).split()
    lines, current = [], ""
    for w in words:
        if len(current) + len(w) + 1 <= max_chars:
            current = (current + " " + w).strip()
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return "\n".join(lines) if lines else str(text)

def draw_stroked_text(draw, pos, text, font, fill, stroke_fill=(0, 0, 0), stroke_width=6):
    """어떤 버전에서도 에러가 나지 않는 안전한 외곽선 및 다중 줄 텍스트 렌더링"""
    x, y = pos
    lines = text.split("\n")
    line_height = int(font.size * 1.28)
    total_h = len(lines) * line_height
    start_y = y - (total_h // 2) + (line_height // 2)

    for i, line in enumerate(lines):
        ly = start_y + i * line_height
        # 외곽선 먼저 그리기
        for dx in range(-stroke_width, stroke_width + 1, 2):
            for dy in range(-stroke_width, stroke_width + 1, 2):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, ly + dy), line, font=font, fill=stroke_fill, anchor="mm")
        # 본문 글자 그리기
        draw.text((x, ly), line, font=font, fill=fill, anchor="mm")

async def _edge_tts_save(text, out_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, VOICE, rate=SPEECH_RATE)
    await communicate.save(out_path)

def generate_fast_audio(text, out_path):
    """1순위: 신경망 고속 AI 음성 / 실패 시: 백업 TTS 생성 후 FFmpeg 1.35배속 가속"""
    try:
        asyncio.run(_edge_tts_save(text, out_path))
        if os.path.exists(out_path) and os.path.getsize(out_path) > 500:
            return
    except Exception as e:
        print(f"⚠️ Edge-TTS 우회 작동 (사유: {e}) -> 고속 백업 엔진 가동")

    from gtts import gTTS
    raw_mp3 = "raw_" + out_path
    tts = gTTS(text=text, lang='ko')
    tts.save(raw_mp3)
    # 말 속도를 1.35배 빠르게 가속 (쇼츠 전용 스피드)
    subprocess.run([
        "ffmpeg", "-y", "-i", raw_mp3,
        "-filter:a", "atempo=1.35",
        "-vn", out_path
    ], check=True)
    if os.path.exists(raw_mp3):
        os.remove(raw_mp3)

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
    canvas = Image.new("RGB", (1080, 1920), (20, 22, 28))
    draw = ImageDraw.Draw(canvas)

    f_hook = get_font(66)
    f_badge = get_font(42)
    f_sub = get_font(74)
    f_card_title = get_font(50)
    f_card_body = get_font(40)

    # 1. 상단 노란색 질문 훅 타이틀
    top_hook = scene.get("top_hook", "오늘의 추천 꿀템!")
    draw_stroked_text(draw, (540, 220), top_hook, f_hook, fill=(255, 225, 60), stroke_width=6)

    # 2. 중앙 라운드 카드 영역 (Y: 350 ~ 1210)
    card_box = [70, 350, 1010, 1210]
    scene_type = scene.get("type", "image")

    if scene_type == "image":
        draw.rounded_rectangle(card_box, radius=45, fill=(255, 255, 255))
        resized = ImageOps.fit(prod_img, (860, 780), Image.Resampling.LANCZOS)
        canvas.paste(resized, (110, 390))

    elif scene_type == "spec":
        draw.rounded_rectangle(card_box, radius=45, fill=(245, 247, 252))
        thumb = ImageOps.fit(prod_img, (300, 300), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (390, 385))
        draw_stroked_text(draw, (540, 745), wrap_text(title, 18), f_card_title, fill=(25, 25, 25), stroke_fill=(255, 255, 255), stroke_width=2)
        y_pos = 860
        for sp in scene.get("specs", []):
            draw.rounded_rectangle([115, y_pos, 965, y_pos + 82], radius=20, fill=(30, 35, 45))
            draw.text((540, y_pos + 41), f"V  {sp}", font=get_font(35), fill=(255, 255, 255), anchor="mm")
            y_pos += 102

    elif scene_type == "checklist":
        draw.rounded_rectangle(card_box, radius=45, fill=(12, 14, 18), outline=(75, 80, 95), width=4)
        draw.text((540, 450), "이런 분께 맞아요", font=get_font(60), fill=(255, 255, 255), anchor="mm")
        y_pos = 580
        for chk in scene.get("checks", []):
            draw.ellipse([125, y_pos - 28, 185, y_pos + 32], fill=(255, 205, 0))
            draw.text((155, y_pos + 2), "V", font=get_font(36), fill=(0, 0, 0), anchor="mm")
            draw.text((215, y_pos), chk, font=f_card_body, fill=(240, 240, 240), anchor="lm")
            y_pos += 130

        draw.rounded_rectangle([125, 1010, 955, 1120], radius=25, fill=(35, 38, 48))
        draw.text((540, 1065), f"추천 꿀템 NO.{p_id} · 빠른 출고 · 만족도 최상", font=get_font(35), fill=(200, 205, 220), anchor="mm")

    elif scene_type == "cta":
        draw.rounded_rectangle(card_box, radius=45, fill=(255, 255, 255))
        thumb = ImageOps.fit(prod_img, (480, 480), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (300, 385))
        draw.rounded_rectangle([200, 920, 880, 1030], radius=30, fill=(255, 200, 0))
        draw.text((540, 975), f"상품 번호 [ {p_id}번 ]", font=get_font(52), fill=(0, 0, 0), anchor="mm")
        draw.text((540, 1110), wrap_text(title, 18), font=get_font(42), fill=(30, 30, 30), anchor="mm")

    # 3. 하단 노란색 알약 배지
    badge_text = scene.get("badge", f"추천 꿀템 NO. {p_id}")
    badge_w = min(max(len(badge_text) * 40 + 80, 460), 960)
    draw.rounded_rectangle(
        [540 - badge_w // 2, 1300, 540 + badge_w // 2, 1395],
        radius=45, fill=(255, 205, 0)
    )
    draw.text((540, 1347), badge_text, font=f_badge, fill=(15, 15, 15), anchor="mm")

    # 4. 하단 메인 굵은 자막
    sub_text = wrap_text(scene.get("sub", title), max_chars=13)
    draw_stroked_text(draw, (540, 1530), sub_text, f_sub, fill=(255, 255, 255), stroke_width=8)

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

    # 만약 scenes가 비어있다면 기본 3씬 자동 구성
    if not scenes:
        scenes = [
            {"top_hook": "아직도 불편하게 쓰세요?", "badge": f"추천 꿀템 NO.{p_id}", "sub": title, "tts": f"요즘 난리 난 추천 꿀템, {title}!", "type": "image"},
            {"top_hook": "나한테 맞을까?", "badge": "구매 전 필수 체크", "sub": "삶의 질 수직 상승!", "tts": "실용성과 가성비를 모두 챙기고 싶은 분께 딱 맞아요.", "type": "checklist", "checks": ["매일 쓰는 생활용품 업그레이드", "깔끔한 정리와 위생이 필요한 분", "가성비 좋은 꿀템을 찾는 분"]},
            {"top_hook": "어디서 살 수 있을까?", "badge": "프로필 링크 클릭", "sub": f"[{p_id}번]을 검색하세요!", "tts": f"지금 바로 프로필 링크에서 {p_id}번을 검색해 보세요!", "type": "cta"}
        ]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_mp4 = os.path.join(OUTPUT_DIR, f"shorts_no_{p_id}.mp4")

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

    for idx, scene in enumerate(scenes):
        frame_file = f"scene_{idx}.jpg"
        audio_file = f"scene_{idx}.mp3"
        seg_mp4 = f"segment_{idx}.mp4"
        temp_files.extend([frame_file, audio_file, seg_mp4])

        draw_scene_frame(scene, prod_img, p_id, title, frame_file)

        tts_text = scene.get("tts", title)
        if idx == len(scenes) - 1:
            tts_text = f"지금 바로 프로필 링크에서 {p_id}번을 검색해 보세요!"
        generate_fast_audio(tts_text, audio_file)

        dur = get_audio_duration(audio_file)
        frames = int(dur * 30) + 5
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", frame_file,
            "-i", audio_file,
            "-vf", f"zoompan=z='min(zoom+0.0012,1.06)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30",
            "-t", str(dur),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            seg_mp4
        ]
        subprocess.run(cmd, check=True)
        segment_files.append(seg_mp4)

    concat_txt = "concat_list.txt"
    temp_files.append(concat_txt)
    with open(concat_txt, "w", encoding="utf-8") as f:
        for seg in segment_files:
            f.write(f"file '{seg}'\n")

    # 클립 병합 시 오디오/비디오 코덱 재정렬로 무결성 보장
    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_txt,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        output_mp4
    ]
    subprocess.run(concat_cmd, check=True)

    for tf in temp_files:
        if os.path.exists(tf):
            os.remove(tf)

    print(f"🎬 프로급 다중 씬 쇼츠 생성 완료: {output_mp4}")

if __name__ == "__main__":
    make_video()
