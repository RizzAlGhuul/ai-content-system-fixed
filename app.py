import os
import requests
from moviepy.editor import AudioFileClip, VideoFileClip, CompositeVideoClip

RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY")
RUNWAY_URL = "https://api.runwayml.com/v1/inference/stable-diffusion"
FALLBACK_VIDEO_URL = "https://your-fallback-storage.com/default.mp4"  # Replace with a working fallback video URL

def generate_video_with_runway(prompt_text, audio_path, output_path):
    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "input": {
            "prompt": prompt_text
        }
    }

    video_path = "/tmp/video.mp4"

    try:
        print("Requesting image from Runway...")
        response = requests.post(RUNWAY_URL, headers=headers, json=payload)
        response.raise_for_status()

        # Expecting a JSON response with an image/video URL
        result = response.json()
        image_url = result.get("output")  # Update key if needed

        if not image_url:
            raise ValueError("Runway response did not contain 'output'")

        print("Downloading video from Runway output...")
        vid_resp = requests.get(image_url)
        vid_resp.raise_for_status()

        with open(video_path, "wb") as f:
            f.write(vid_resp.content)

    except Exception as e:
        print(f"[WARNING] Runway failed: {e}")
        print("[INFO] Attempting to download fallback video...")
        try:
            fallback_response = requests.get(FALLBACK_VIDEO_URL)
            fallback_response.raise_for_status()
            with open(video_path, "wb") as f:
                f.write(fallback_response.content)
        except Exception as fallback_error:
            print(f"[ERROR] Fallback video download failed: {fallback_error}")
            return

    # Validate video exists
    if not os.path.exists(video_path) or os.path.getsize(video_path) < 10000:
        print("[ERROR] Video file is missing or invalid after all attempts.")
        return

    # Merge audio and video
    try:
        video_clip = VideoFileClip(video_path)
        audio_clip = AudioFileClip(audio_path)
        final_clip = video_clip.set_audio(audio_clip)
        final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac")
        print("[SUCCESS] Video generated and saved to:", output_path)

    except Exception as merge_error:
        print(f"[ERROR] MoviePy merge failed: {merge_error}")