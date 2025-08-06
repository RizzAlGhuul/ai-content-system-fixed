import os
import requests
import time
import json
import logging
from flask import Flask, jsonify, render_template, request
from openai import OpenAI
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from pytrends.request import TrendReq
from dotenv import load_dotenv
from moviepy.editor import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logging.info("Starting app initialization...")

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
RUNWAY_API_KEY = os.getenv('RUNWAY_API_KEY')
AYRSHARE_API_KEY = os.getenv('AYRSHARE_API_KEY')
NICHE = os.getenv('NICHE', 'personal finance')
AFFILIATE_LINK = os.getenv('AFFILIATE_LINK', 'https://example.com/aff')

missing_keys = []
if not OPENAI_API_KEY:
    missing_keys.append("OPENAI_API_KEY")
if not ELEVENLABS_API_KEY:
    missing_keys.append("ELEVENLABS_API_KEY")
if not RUNWAY_API_KEY:
    missing_keys.append("RUNWAY_API_KEY")
if not AYRSHARE_API_KEY:
    missing_keys.append("AYRSHARE_API_KEY")

if missing_keys:
    logging.error(f"Missing the following API keys: {', '.join(missing_keys)}")
    raise ValueError("Missing required API keys")

openai_client = OpenAI(api_key=OPENAI_API_KEY)
elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

TEMP_DIR = '/tmp/' if 'DYNO' in os.environ else ''

scheduler = BackgroundScheduler()
scheduler.add_job(lambda: generate_content(num_trends=3), 'cron', hour='8,16')

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/generate', methods=['GET', 'POST'])
def generate_content(num_trends=1):
    results = []
    try:
        logging.info("Starting content generation")
        pytrends = TrendReq(hl='en-US', tz=360)
        trends = []
        try:
            pytrends.build_payload(kw_list=[NICHE], cat=0, timeframe='now 1-d')
            trends_df = pytrends.related_queries().get(NICHE, {}).get('top', None)
            if trends_df is not None:
                trends = trends_df['query'].tolist()
        except Exception as e:
            logging.warning(f"Trend fetch failed: {str(e)}")
            trends = ["Investment tips 2025", "How to save money fast", "Passive income ideas"]

        filtered_trends = [t for t in trends if NICHE.lower() in t.lower()] or ["Fallback trend in " + NICHE]
        trends_to_use = filtered_trends[:num_trends]

        for trend in trends_to_use:
            logging.info(f"Processing trend: {trend}")
            for _ in range(3):
                prompt = f"""
                Analyze '{trend}' in {NICHE} niche for short-form video. 
                Output JSON: \"script\", \"title\", \"description\", \"hashtags\" (5).
                Affiliate link: {AFFILIATE_LINK}
                """
                try:
                    response = openai_client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    raw_content = response.choices[0].message.content or ""
                    raw_content = raw_content.strip()
                    if raw_content.startswith("```json") or raw_content.startswith("````"):
                        raw_content = raw_content.removeprefix("```json").removeprefix("````").removesuffix("```")
                    data = json.loads(raw_content)
                except Exception as e:
                    logging.error(f"OpenAI response parsing failed: {str(e)}")
                    continue

                script = data.get('script', '')[:1000]
                title = data.get('title', 'Trend Video')
                desc = data.get('description', '') + f"\n{AFFILIATE_LINK}"
                hashtags = data.get('hashtags', [])

                score, feedback = verify_quality("script analysis", script + " " + desc)
                if score >= 7:
                    break
            else:
                continue

            audio_path = os.path.join(TEMP_DIR, "voiceover.mp3")
            logging.info("Generating voiceover")
            audio_stream = elevenlabs_client.text_to_speech.convert(
                text=script,
                voice_id="21m00Tcm4TlvDq8ikWAM",
                model_id="eleven_turbo_v2",
                voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
                output_format="mp3_44100_128"
            )
            with open(audio_path, "wb") as f:
                for chunk in audio_stream:
                    f.write(chunk)

            logging.info("Starting Runway image generation")
            headers = {
                "Authorization": f"Bearer {RUNWAY_API_KEY}",
                "Content-Type": "application/json"
            }
            image_url = "https://images.unsplash.com/photo-1600585154340-be6161a56a0c"
            try:
                image_payload = {"promptText": script, "model": "gen4_image", "ratio": "720:1280"}
                resp = requests.post("https://api.runwayml.com/v1/text_to_image", headers=headers, json=image_payload)
                if resp.status_code == 200:
                    task_id = resp.json().get("id")
                    if not task_id:
                        raise ValueError("Runway image task ID not returned")
                    for _ in range(90):
                        poll = requests.get(f"https://api.runwayml.com/v1/tasks/{task_id}", headers=headers)
                        poll_json = poll.json()
                        logging.info(f"Runway image task poll: {json.dumps(poll_json, indent=2)}")
                        status = poll_json.get("status")
                        if status == "SUCCEEDED":
                            image_url = poll_json.get("output", [{}])[0]
                            break
                        elif status == "FAILED":
                            break
                        time.sleep(5)
            except Exception as e:
                logging.warning(f"Runway image fallback: {str(e)}")

            video_path = os.path.join(TEMP_DIR, "video.mp4")
            merged_path = os.path.join(TEMP_DIR, "merged.mp4")
            video_downloaded = False
            try:
                video_payload = {
                    "promptImage": image_url,
                    "promptText": script,
                    "model": "gen3a_turbo",
                    "ratio": "720:1280",
                    "seed": 12345
                }
                resp = requests.post("https://api.runwayml.com/v1/image_to_video", headers=headers, json=video_payload)
                if resp.status_code == 200:
                    task_id = resp.json().get("id")
                    if not task_id:
                        raise ValueError("Runway video task ID not returned")
                    for _ in range(90):
                        poll = requests.get(f"https://api.runwayml.com/v1/tasks/{task_id}", headers=headers)
                        poll_json = poll.json()
                        logging.info(f"Runway video task poll: {json.dumps(poll_json, indent=2)}")
                        status = poll_json.get("status")
                        if status == "SUCCEEDED":
                            output = poll_json.get("output")
                            video_url = None
                            if isinstance(output, list) and output:
                                video_url = output[0].get("uri") or output[0].get("video")
                            elif isinstance(output, dict):
                                video_url = output.get("
