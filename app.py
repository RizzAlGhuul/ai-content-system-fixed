from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import httpx
import moviepy.editor as mp
import os

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Scheduler setup
scheduler = BackgroundScheduler()
scheduler.start()

@app.route("/")
def home():
    return jsonify({"message": "Welcome to TechTribe Collective!"})

@app.route("/generate")
def generate():
    try:
        logging.info("Starting content generation")

        # Placeholder trend
        trend = "personal finance news"
        logging.info(f"Processing trend: {trend}")

        # Call OpenAI for script
        openai_response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}", "Content-Type": "application/json"},
            json={"model": "gpt-4", "messages": [{"role": "user", "content": trend}]}
        )
        logging.info("Verifying quality for script analysis")
        script = openai_response.json()["choices"][0]["message"]["content"]

        # Call ElevenLabs for voiceover
        logging.info("Generating voiceover")
        voice_response = httpx.post(
            "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM?output_format=mp3_44100_128",
            headers={"xi-api-key": os.getenv("ELEVENLABS_API_KEY"), "Content-Type": "application/json"},
            json={"text": script}
        )
        with open("/tmp/audio.mp3", "wb") as f:
            f.write(voice_response.content)

        # Call Runway for image generation (fallback handling)
        logging.info("Starting Runway image generation")
        try:
            runway_response = httpx.post(
                "https://api.runwayml.com/v1/gen/image",
                headers={"Authorization": f"Bearer {os.getenv('RUNWAY_API_KEY')}", "Content-Type": "application/json"},
                json={"prompt": trend}
            )
            runway_response.raise_for_status()
            image_url = runway_response.json().get("image_url")
            image_data = httpx.get(image_url).content
            with open("/tmp/image.jpg", "wb") as f:
                f.write(image_data)
        except Exception as e:
            logging.warning(f"Runway fallback: {e}")

        # Dummy placeholder video for merge
        logging.info("Merging video and audio")
        try:
            clip = mp.ImageClip("/tmp/image.jpg", duration=10).set_audio(mp.AudioFileClip("/tmp/audio.mp3"))
            clip.write_videofile("/tmp/video.mp4", codec="libx264", fps=24)
        except Exception as e:
            logging.error(f"MoviePy merge failed: {e}")

        return jsonify({"status": "Content generated."})

    except Exception as e:
        logging.exception("Unhandled error in /generate")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))