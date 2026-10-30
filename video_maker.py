import json, os, subprocess, asyncio, urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageOps

PRODUCTS_FILE = 'products.json'
OUTPUT_DIR = 'videos'

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
    return ImageFont.load_default()

async def generate_tts(text, output_audio_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, "ko-KR-SunHiNeural", rate="+15%")
    await communicate.save(output_audio_path)

def create_scene_frame(img_path, badge_text, hook_text, sub_text, out_img_path):
    img = Image.open(img_path).convert("RGB")
    img = ImageOps.fit(img, (1080, 1920), method=Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(img, "RGBA")

    font_badge = get_font(48)
    font_hook = get_font(68)
    font_sub = get_font(54)

    # 1. 상단 노란색 배지 박스
    bbox_b = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw, bh = bbox_b[2] - bbox_b[0], bbox_b[3] - bbox_b[1]
    bx = (1080 - bw) // 2
    by = 180
    draw.rounded_rectangle([bx - 30, by - 15, bx + bw + 30, by + bh + 20], radius=20, fill=(255, 215, 0, 240))
    draw.text((bx, by), badge_text, font=font_badge, fill=(0, 0, 0, 255))

    # 2. 상단 메인 후킹 자막 박스
    bbox_h = draw.textbbox((0, 0), hook_text, font=font_hook)
    hw, hh = bbox_h[2] - bbox_h[0], bbox_h[3] - bbox_h[1]
    hx = (1080 - hw) // 2
    hy = 290
    draw.rounded_rectangle([hx - 35, hy - 20, hx + hw + 35, hy + hh + 25], radius=20, fill=(0, 0, 0, 200))
    draw.text((hx, hy), hook_text, font=font_hook, fill=(255, 255, 255, 255))

    # 3. 하단 보조 설명 자막 박스
    if sub_text:
        bbox_s = draw.textbbox((0, 0), sub_text, font=font_sub)
        sw, sh = bbox_s[2] - bbox_s[0], bbox_s[3] - bbox_s[1]
        sx = (1080 - sw) // 2
        sy = 1520
        draw.rounded_rectangle([sx - 35, sy - 20, sx + sw + 35, sy + sh + 25], radius=20, fill=(0, 0, 0, 210))
        draw.text((sx, sy), sub_text, font=font_sub, fill=(0, 255, 200, 255))

    img.save(out_img_path, quality=95)

def render_shorts():
    if not os.path.exists(PRODUCTS_FILE):
        raise RuntimeError("products.json 파일이 없습니다.")
    with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
        products = json.load(f)
    if not products:
        raise RuntimeError("상품 데이터가 비어 있습니다.")

    latest = products[0]
    p_id = latest.get('id', 1)
    scenes = latest.get('scenes', [])

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_mp4 = os.path.join(OUTPUT_DIR, f"shorts_no_{p_id}.mp4")

    print(f"🎬 [2단계] 총 {len(scenes)}개 장면 개별 렌더링 및 병합 시작...")

    scene_clips = []
    temp_files = []
    req_headers = {'User-Agent': 'Mozilla/5.0'}

    for idx, scene in enumerate(scenes):
        print(f"   🎞️ 장면 {idx+1}/{len(scenes)} 제작 중: {scene.get('hook')}")
        raw_img = f"temp_raw_{idx}.jpg"
        framed_img = f"temp_framed_{idx}.jpg"
        audio_mp3 = f"temp_audio_{idx}.mp3"
        clip_mp4 = f"temp_clip_{idx}.mp4"
        temp_files.extend([raw_img, framed_img, audio_mp3, clip_mp4])

        # 장면별 이미지 다운로드
        img_url = scene.get('image')
        req = urllib.request.Request(img_url, headers=req_headers)
        with urllib.request.urlopen(req) as resp, open(raw_img, 'wb') as out:
            out.write(resp.read())

        # 이미지 위에 상/하단 자막 및 배지 디자인 합성
        create_scene_frame(
            raw_img,
            scene.get('badge', f'NO.{p_id}'),
            scene.get('hook', ''),
            scene.get('sub', ''),
            framed_img
        )

        # 장면별 아나운서 TTS 생성
        asyncio.run(generate_tts(scene.get('tts', ''), audio_mp3))

        # 장면별 비디오 클립 생성 (미세한 줌인 애니메이션 추가로 동적인 느낌 부여)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", "30", "-i", framed_img,
            "-i", audio_mp3,
            "-vf", "scale=1200:2133,zoompan=z='min(zoom+0.0005,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            clip_mp4
        ]
        subprocess.run(cmd, check=True)
        scene_clips.append(clip_mp4)

    # 3개 장면 클립을 하나의 쇼츠 영상으로 이어붙이기
    concat_txt = "concat_list.txt"
    temp_files.append(concat_txt)
    with open(concat_txt, "w", encoding="utf-8") as f:
        for clip in scene_clips:
            f.write(f"file '{clip}'\n")

    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-c", "copy",
        output_mp4
    ]
    subprocess.run(concat_cmd, check=True)

    for p in temp_files:
        if os.path.exists(p):
            os.remove(p)

    print(f"🎉 [완성] 3개 장면 전환 + 상/하단 자막 + TTS 결합 쇼츠 생성 완료 -> {output_mp4}")

if __name__ == "__main__":
    render_shorts()
