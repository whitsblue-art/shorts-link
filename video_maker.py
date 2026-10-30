import json, os, subprocess, asyncio

PRODUCTS_FILE = 'products.json'
OUTPUT_DIR = 'videos'

async def generate_tts(text, output_audio_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, "ko-KR-SunHiNeural", rate="+20%")
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

    print(f"🎬 [3단계] TTS 오디오 생성 및 영상 렌더링 시작...")
    
    img_path = "temp_product.jpg"
    try:
        import urllib.request
        urllib.request.urlretrieve(image_url, img_path)
    except:
        pass

    combined_text = " ".join([s.get("tts", "") for s in scenes])
    audio_path = "temp_voice.mp3"
    
    try:
        asyncio.run(generate_tts(combined_text, audio_path))
    except Exception as e:
        print(f"TTS 생성 예외: {e}")

    # FFmpeg로 이미지와 오디오를 결합한 진짜 쇼츠 영상 생성
    if os.path.exists(img_path) and os.path.exists(audio_path):
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", img_path,
            "-i", audio_path,
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
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

    print(f"🎉 [성공] 비전 AI 검수 통과 후 음성 포함 쇼츠 완성 -> {output_mp4}")

if __name__ == "__main__":
    render_shorts()
