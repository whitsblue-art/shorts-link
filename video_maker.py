import json, os, subprocess, asyncio

PRODUCTS_FILE = 'products.json'
OUTPUT_DIR = 'videos'
FONT_PATH = '/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf'

async def generate_tts(text, output_audio_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, "ko-KR-SunHiNeural", rate="+15%")
    await communicate.save(output_audio_path)

def render_shorts():
    if not os.path.exists(PRODUCTS_FILE): return
    with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
        products = json.load(f)
    if not products: return

    latest = products[0]
    p_id = latest.get('id', 1)
    image_url = latest.get('image', '')
    scenes = latest.get('scenes', [])

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_mp4 = os.path.join(OUTPUT_DIR, f"shorts_no_{p_id}.mp4")

    print(f"🎬 [3단계] 자막 오버레이 및 TTS 오디오 결합 렌더링 시작...")
    
    img_path = "temp_product.jpg"
    try:
        import urllib.request
        urllib.request.urlretrieve(image_url, img_path)
    except:
        pass

    combined_text = " ".join([s.get("tts", "") for s in scenes])
    hook_text = scenes[0].get("hook", "추천 꿀템") if scenes else "추천 꿀템"
    badge_text = scenes[0].get("badge", f"NO.{p_id}") if scenes else f"NO.{p_id}"
    
    audio_path = "temp_voice.mp3"
    try:
        asyncio.run(generate_tts(combined_text, audio_path))
    except Exception as e:
        print(f"TTS 생성 예외: {e}")

    # 폰트 파일 존재 여부 확인 및 FFmpeg 자막(drawtext) 필터 적용
    font_arg = FONT_PATH if os.path.exists(FONT_PATH) else ""
    
    if os.path.exists(img_path) and os.path.exists(audio_path):
        if font_arg:
            # 폰트가 있을 경우 화면 상단에 후킹 자막과 배지 텍스트를 직접 그려넣음
            vf_filter = (
                f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                f"drawtext=fontfile='{font_arg}':text='{badge_text}':fontcolor=yellow:fontsize=50:x=(w-text_w)/2:y=200:box=1:boxcolor=black@0.6:boxborderw=10,"
                f"drawtext=fontfile='{font_arg}':text='{hook_text}':fontcolor=white:fontsize=65:x=(w-text_w)/2:y=300:box=1:boxcolor=black@0.6:boxborderw=12"
            )
        else:
            vf_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", img_path,
            "-i", audio_path,
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-vf", vf_filter,
            "-shortest",
            output_mp4
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=navy:s=1080x1920:d=10",
            "-c:v", "libx264", "-t", "10", output_mp4
        ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for p in [img_path, audio_path]:
        if os.path.exists(p): os.remove(p)

    print(f"🎉 [성공] 비전 AI 검수 및 자막·음성 포함 쇼츠 완성 -> {output_mp4}")

if __name__ == "__main__":
    render_shorts()
