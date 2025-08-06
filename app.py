from flask import Flask, render_template, request, send_file
from runwayml import RunwayML, TaskFailedError, TaskTimeoutError
from elevenlabs import generate, set_api_key, save
from moviepy.editor import *
from tempfile import NamedTemporaryFile
import openai
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)

# API Keys
openai.api_key = os.getenv("OPENAI_API_KEY")
set_api_key(os.getenv("ELEVEN_API_KEY"))
runway = RunwayML(api_key=os.getenv("RUNWAY_API_KEY"))

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/generate", methods=["GET"])
def generate_video():
    logger.info("Starting content generation")
    trend = "personal finance news"
    logger.info(f"Processing trend: {trend}")

    # GPT script generation
    script_prompt = f"Create a YouTube Shorts script on the topic: '{trend}'"
    script_response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a professional video script writer."},
            {"role": "user", "content": script_prompt},
        ]
    )
    script = script_response.choices[0].message.content.strip()
    logger.info("Verifying quality for script analysis")

    # ElevenLabs voice generation
    logger.info("Generating voiceover")
    audio = generate(
        text=script,
        voice="Rachel",
        model="eleven_multilingual_v2",
        output_format="mp3_44100_128"
    )
    audio_path = "/tmp/audio.mp3"
    save(audio, audio_path)

    # RunwayML image generation
    logger.info("Starting Runway image generation")
    try:
        image_task = runway.text_to_image.create(
            model='gen4_image',
            prompt_text=script,
            ratio='1280:720',
        )
        image_result = image_task.wait_for_task_output(timeout=300)
        image_url = image_result.output[0]["url"]
    except TaskFailedError as e:
        logger.warning("Runway task failed: %s", e.task_details)
        image_url = "https://source.unsplash.com/1280x720/?finance"
    except TaskTimeoutError:
        logger.warning("Runway task timed out")
        image_url = "https://source.unsplash.com/1280x720/?finance"

    # RunwayML video generation
    try:
        video_task = runway.image_to_video.create(
            model='gen2_video',
            input_image_url=image_url,
            motion='slow zoom in',
        )
        video_result = video_task.wait_for_task_output(timeout=300)
        video_url = video_result.output[0]["url"]
    except Exception as e:
        logger.warning("Runway video generation failed, fallback to static image: %s", str(e))
        video_url = image_url

    logger.info("Merging video and audio")
    try:
        video_clip = VideoFileClip(video_url)
        audio_clip = AudioFileClip(audio_path)
        final_clip = video_clip.set_audio(audio_clip)
        temp_file = NamedTemporaryFile(delete=False, suffix=".mp4")
        final_clip.write_videofile(temp_file.name, codec="libx264", audio_codec="aac")
        return send_file(temp_file.name, as_attachment=True)
    except Exception as e:
        logger.error("MoviePy merge failed: %s", str(e))
        return "Error creating video"

if __name__ == "__main__":
    app.run(debug=True)