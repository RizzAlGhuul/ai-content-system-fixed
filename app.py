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
            try:
                image_payload = {
                    "modelVersionId": "stable-diffusion-v1-5",  # example model version
                    "input": {
                        "prompt": script,
                        "width": 512,
                        "height": 768
                    }
                }
                resp = requests.post("https://api.runwayml.com/v1/inference", headers=headers, json=image_payload)
                resp.raise_for_status()
                image_url = resp.json().get("output", {}).get("image") or "https://images.unsplash.com/photo-1600585154340-be6161a56a0c"
            except Exception as e:
                logging.warning(f"Runway fallback: {str(e)}")
                image_url = "https://images.unsplash.com/photo-1600585154340-be6161a56a0c"

            logging.info("Merging video and audio")
            try:
                video_path = os.path.join(TEMP_DIR, "video.mp4")
                merged_path = os.path.join(TEMP_DIR, "merged.mp4")

                fallback_video = "https://filesamples.com/samples/video/mp4/sample_640x360.mp4"
                response = requests.get(fallback_video)
                with open(video_path, "wb") as f:
                    f.write(response.content)

                if os.path.getsize(video_path) < 1024:
                    raise ValueError("Downloaded fallback video is too small or invalid.")

                video_clip = VideoFileClip(video_path)
                audio_clip = AudioFileClip(audio_path)
                if audio_clip.duration < video_clip.duration:
                    raise ValueError("Audio is shorter than video, cannot merge")
                audio_clip = audio_clip.subclip(0, video_clip.duration)
                caption_clip = TextClip("Trend: " + trend, fontsize=24, color='white').set_position('bottom').set_duration(video_clip.duration)
                merged = CompositeVideoClip([video_clip.set_audio(audio_clip), caption_clip])
                merged.write_videofile(merged_path, codec="libx264", audio_codec="aac")
                os.remove(audio_path)
                os.remove(video_path)
                os.remove(merged_path)
            except Exception as e:
                logging.error(f"MoviePy merge failed: {str(e)}")
                continue

            results.append({"trend": trend, "status": "success"})

        return jsonify({"status": "success", "results": results})

    except Exception as e:
        logging.error(f"Error in generate_content: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})

def verify_quality(output_type, content):
    logging.info(f"Verifying quality for {output_type}")
    prompt = f"Review this {output_type} for quality in {NICHE} niche: {content}. Score 1-10 for relevance, engagement, monetization potential. Output JSON: 'score' (int), 'feedback' (string)."
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        raw_content = response.choices[0].message.content.strip()
        if raw_content.startswith("```json") or raw_content.startswith("````"):
            raw_content = raw_content.removeprefix("```json").removeprefix("````").removesuffix("```")
        result = json.loads(raw_content)
        return result.get('score', 5), result.get('feedback', '')
    except Exception as e:
        logging.warning(f"Quality check parse failed: {str(e)}")
        return 5, "Failed to parse response"

if __name__ == '__main__':
    try:
        scheduler.start()
        logging.info("Scheduler started successfully.")
        app.run(debug=False)
    except Exception as e:
        logging.critical(f"App failed to start: {str(e)}")