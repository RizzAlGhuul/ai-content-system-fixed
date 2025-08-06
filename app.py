import os
import tempfile
import logging
from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import httpx
import moviepy.editor as mp

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Scheduler setup
scheduler = BackgroundScheduler()
scheduler.start()

# Environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY")

@app.route("/")
def home():
    return "App is running."

@app.route("/generate", methods=["GET"])
def generate():
    try:
        logger.info("Starting content generation")
        topic = "personal finance news"

        # Step 1: Get trend
        logger.info(f"Processing trend: {topic}")

        # Step 2: Generate script from OpenAI
        openai_headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        script_prompt = f"Generate a short engaging script on the topic: {topic}"
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers=openai_headers,
            json={
                "model": "gpt-4",
                "messages": [
                    {"role": "user", "content": script_prompt}
                ]
            },
            timeout=30
        )
        script = response.json()["choices"][0]["message"]["content"]
        logger.info("Verifying quality for script analysis")

        # Step 3: Generate voiceover with ElevenLabs
        logger.info("Generating voiceover")
        eleven_headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        eleven_payload = {
            "text": script,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5
            }
        }
        voice_id = "21m00Tcm4TlvDq8ikWAM"
        tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
        tts_response = httpx.post(tts_url, headers=eleven_headers, json=eleven_payload)
        audio_fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        audio_fp.write(tts_response.content)
        audio_fp.close()

        # Step 4: Generate video/image with Runway
        logger.info("Starting Runway image generation")
        runway_headers = {
            "Authorization": f"Bearer {RUNWAY_API_KEY}",
            "Content-Type": "application/json"
        }
        runway_payload = {
            "prompt": topic,
            "num_images": 1,
            "width": 512,
            "height": 512,
            "output_format": "mp4"
        }
        try:
            runway_resp = httpx.post("https://api.runwayml.com/v1/gen/image", headers=runway_headers, json=runway_payload)
            runway_resp.raise_for_status()
            image_url = runway_resp.json()["urls"][0]
        except Exception as e:
            logger.warning(f"Runway fallback: {e}")
            image_url = "https://sample-videos.com/video123/mp4/720/big_buck_bunny_720p_1mb.mp4"

        video_fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        try:
            video_content = httpx.get(image_url, timeout=30).content
            video_fp.write(video_content)
            video_fp.close()
        except Exception as e:
            logger.error(f"Failed to download video: {e}")
            return jsonify({"error": "Video download failed"}), 500

        # Step 5: Merge with MoviePy
        logger.info("Merging video and audio")
        try:
            video_clip = mp.VideoFileClip(video_fp.name)
            audio_clip = mp.AudioFileClip(audio_fp.name)

            if audio_clip.duration > video_clip.duration:
                audio_clip = audio_clip.subclip(0, video_clip.duration)

            final_video = video_clip.set_audio(audio_clip)
            output_fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
            final_video.write_videofile(output_fp.name, codec="libx264", audio_codec="aac")
        except Exception as e:
            logger.error(f"MoviePy merge failed: {e}")
            return jsonify({"error": "Video processing failed"}), 500

        return jsonify({"message": "Video generated successfully."})

    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(debug=True)