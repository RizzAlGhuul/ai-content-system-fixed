from flask import Flask, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler
from runwayml import RunwayML, TaskFailedError
from elevenlabs import ElevenLabs, VoiceSettings, Voice
import httpx
import os
import uuid

app = Flask(__name__)

# Initialize ElevenLabs and Runway clients
voice_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
runway_client = RunwayML(api_key=os.getenv("RUNWAY_API_KEY"))

scheduler = BackgroundScheduler()
scheduler.start()

def get_trending_topic():
    return "personal finance news"

def generate_script(trend):
    return f"Here's a quick update on {trend}. Stay informed and take control of your financial future!"

def verify_script_quality(script):
    return True

def generate_voiceover(script):
    audio = voice_client.generate(
        text=script,
        voice=Voice(voice_id="21m00Tcm4TlvDq8ikWAM"),
        model="eleven_monolingual_v1",
        voice_settings=VoiceSettings(stability=0.71, similarity_boost=0.5)
    )
    filename = f"static/audio_{uuid.uuid4()}.mp3"
    with open(filename, "wb") as f:
        f.write(audio)
    return filename

def generate_image(prompt):
    try:
        image_task = runway_client.text_to_image.create(
            model="gen4_image",
            prompt_text=prompt,
            ratio="1360:768",
        )
        result = image_task.wait_for_task_output(timeout=300)
        return result.output[0] if result.output else None
    except TaskFailedError as e:
        print("Image generation failed:", e.task_details)
        return None

def generate_video_and_audio(trend):
    script = generate_script(trend)
    if not verify_script_quality(script):
        return "Script failed quality check"

    audio_path = generate_voiceover(script)
    image_url = generate_image(script)

    if not image_url:
        return "Image generation failed"

    # Heroku doesn't support ffmpeg well, so just return paths for now
    return audio_path, image_url

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/generate")
def generate():
    trend = get_trending_topic()
    result = generate_video_and_audio(trend)
    return str(result)

if __name__ == "__main__":
    app.run(debug=True)