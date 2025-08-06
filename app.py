import os
import uuid
import base64
import tempfile
import logging
from flask import Flask, render_template, request, send_file
from apscheduler.schedulers.background import BackgroundScheduler
from moviepy.editor import AudioFileClip, VideoFileClip, CompositeVideoClip
from runwayml import RunwayML, TaskFailedError
from elevenlabs.client import ElevenLabs
from elevenlabs import Voice, VoiceSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
runway_client = RunwayML()
elevenlabs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

TEMP_DIR = tempfile.gettempdir()

def generate_image(prompt_text, ratio="1280:720"):
    try:
        task = runway_client.text_to_image.create(
            model="gen4_image",
            prompt_text=prompt_text,
            ratio=ratio
        )
        result = task.wait_for_task_output(timeout=300)
        return result.output[0] if result and result.output else None
    except TaskFailedError as e:
        logger.error("Image generation failed: %s", e.task_details)
        return None

def generate_video(image_url):
    try:
        task = runway_client.image_to_video.create(
            model="gen2",
            input_image_url=image_url
        )
        result = task.wait_for_task_output(timeout=300)
        return result.output[0] if result and result.output else None
    except TaskFailedError as e:
        logger.error("Video generation failed: %s", e.task_details)
        return None

def generate_voiceover(text):
    try:
        audio = elevenlabs_client.text_to_speech.convert(
            voice=Voice(voice_id="21m00Tcm4TlvDq8ikWAM"),
            text=text,
            model="eleven_multilingual_v2",
            voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.5)
        )
        audio_path = os.path.join(TEMP_DIR, f"voice_{uuid.uuid4()}.mp3")
        with open(audio_path, "wb") as f:
            f.write(audio)
        return audio_path
    except Exception as e:
        logger.error("Voiceover generation failed: %s", e)
        return None

def merge_audio_video(video_url, audio_path):
    try:
        video_path = os.path.join(TEMP_DIR, f"video_{uuid.uuid4()}.mp4")
        video_response = runway_client._http_client.get(video_url)
        with open(video_path, "wb") as f:
            f.write(video_response.content)

        final_output = os.path.join(TEMP_DIR, f"final_{uuid.uuid4()}.mp4")
        video_clip = VideoFileClip(video_path)
        audio_clip = AudioFileClip(audio_path)
        final_clip = video_clip.set_audio(audio_clip)
        final_clip.write_videofile(final_output, codec="libx264", audio_codec="aac")
        return final_output
    except Exception as e:
        logger.error("Merging audio and video failed: %s", e)
        return None

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/generate")
def generate():
    logger.info("Starting content generation")
    prompt = request.args.get("prompt", "A futuristic city skyline at dusk")
    script_text = f"This is a generated video about: {prompt}"

    image_url = generate_image(prompt)
    if not image_url:
        return "Image generation failed", 500

    video_url = generate_video(image_url)
    if not video_url:
        return "Video generation failed", 500

    voice_path = generate_voiceover(script_text)
    if not voice_path:
        return "Voiceover generation failed", 500

    final_path = merge_audio_video(video_url, voice_path)
    if not final_path:
        return "Video merge failed", 500

    return send_file(final_path, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)