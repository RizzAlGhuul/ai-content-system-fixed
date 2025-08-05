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

load_dotenv()  # Load .env for local dev

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logging.info("Starting app initialization...")

# API Keys and configs from env vars
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
RUNWAY_API_KEY = os.getenv('RUNWAY_API_KEY')
AYRSHARE_API_KEY = os.getenv('AYRSHARE_API_KEY')
NICHE = os.getenv('NICHE', 'personal finance')
AFFILIATE_LINK = os.getenv('AFFILIATE_LINK', 'https://example.com/aff')

# Validate keys
logging.info("Checking API keys...")
if not all([OPENAI_API_KEY, ELEVENLABS_API_KEY, RUNWAY_API_KEY, AYRSHARE_API_KEY]):
    logging.error("Missing one or more API keys in environment variables")
    raise ValueError("Missing API keys")

logging.info("Initializing OpenAI client...")
try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logging.error(f"Failed to initialize OpenAI client: {str(e)}")
    raise

logging.info("Initializing ElevenLabs client...")
elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# Temp file prefix for Heroku
TEMP_DIR = '/tmp/' if 'DYNO' in os.environ else ''

# Scheduler for automated runs
logging.info("Setting up scheduler...")
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: generate_content(num_trends=3), 'cron', hour='8,16')
scheduler.start()
logging.info("Scheduler initialized")

def verify_quality(output_type, content):
    """Quality check agent using OpenAI."""
    logging.info(f"Verifying quality for {output_type}")
    prompt = f"Review this {output_type} for quality in {NICHE} niche: {content}. Score 1-10 for relevance, engagement, monetization potential. Output JSON: 'score' (int), 'feedback' (string)."
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    result = json.loads(response.choices[0].message.content)
    return result.get('score', 5), result.get('feedback', '')

@app.route('/')
def home():
    logging.info("Home endpoint accessed")
    return render_template('index.html')

@app.route('/generate', methods=['GET', 'POST'])
def generate_content(num_trends=1):
    results = []
    try:
        logging.info("Starting content generation")
        # Step 1: Fetch and filter Trends with retries and fallback
        pytrends = TrendReq(hl='en-US', tz=360)
        trends = []
        retries = 0
        max_retries = 3
        while retries < max_retries and not trends:
            try:
                trends = pytrends.trending_searches(pn='united_states')[:10]
                logging.info("Successfully fetched trends from PyTrends")
            except Exception as e:
                logging.warning(f"PyTrends failed: {str(e)}")
                retries += 1
                time.sleep(5)  # Wait before retrying
        if not trends or trends.empty:
            logging.error("No trends from PyTrends; using fallback")
            trends = ["Investment tips 2025", "How to save money fast", "Passive income ideas"]
        else:
            trends = trends.iloc[:, 0].tolist()
        filtered_trends = [t for t in trends if NICHE.lower() in t.lower()] or ["Fallback trend in " + NICHE]
        trends_to_use = filtered_trends[:num_trends]

        for trend in trends_to_use:
            logging.info(f"Processing trend: {trend}")

            # Step 2: Analyze Trend with retries
            retries = 0
            while retries < 3:
                analysis_prompt = f"""
                Analyze '{trend}' in {NICHE} niche for short-form video. 
                Output JSON: "script" (15-30s with hook in first 3s, CTA, affiliate: {AFFILIATE_LINK}), 
                "title", "description", "hashtags" (list of 5 trending).
                """
                analysis_response = openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": analysis_prompt}],
                    response_format={"type": "json_object"}
                )
                analysis_json = json.loads(analysis_response.choices[0].message.content)
                script = analysis_json.get('script', "Default script")[:2048]
                title = analysis_json.get('title', "Trend Video")
                desc = analysis_json.get('description', "Based on trending topic") + f"\n{AFFILIATE_LINK}"
                hashtags = analysis_json.get('hashtags', [])

                score, feedback = verify_quality("script analysis", script + " " + desc)
                logging.info(f"Analysis quality score: {score}, feedback: {feedback}")
                if score >= 7:
                    break
                retries += 1
                logging.warning(f"Low quality ({score}/10), retrying analysis...")

            if score < 7:
                logging.error(f"Failed quality check for trend: {trend}")
                continue

            logging.info(f"Generated script: {script}")

            # Step 3: Generate Voiceover
            logging.info("Generating voiceover")
            audio_stream = elevenlabs_client.text_to_speech.convert(
                text=script,
                voice_id="21m00Tcm4TlvDq8ikWAM",
                model_id="eleven_turbo_v2",
                voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75, style=0.0, use_speaker_boost=True),
                output_format="mp3_44100_128"
            )
            audio_path = TEMP_DIR + "voiceover.mp3"
            with open(audio_path, "wb") as f:
                for chunk in audio_stream:
                    if chunk:
                        f.write(chunk)

            # Step 4: Generate Image then Video with Runway
            headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json"}
            logging.info("Starting Runway image generation")
            image_payload = {
                "promptText": script,
                "model": "gen4_image",
                "ratio": "720:1280"
            }
            logging.info(f"Runway image payload: {json.dumps(image_payload)}")
            image_url = None
            try:
                image_response = requests.post("https://api.runwayml.com/v1/text_to_image", json=image_payload, headers=headers)
                image_response.raise_for_status()
                image_task_id = image_response.json().get("id")
                max_attempts = 60
                for _ in range(max_attempts):
                    poll_response = requests.get(f"https://api.runwayml.com/v1/tasks/{image_task_id}", headers=headers)
                    poll_response.raise_for_status()
                    task_data = poll_response.json()
                    logging.info(f"Runway image task status: {task_data.get('status')}")
                    if task_data.get("status") == "SUCCEEDED":
                        image_url = task_data.get("output", [{}])[0]
                        break
                    elif task_data.get("status") == "FAILED":
                        logging.error(f"Image task failed: {task_data.get('error')}")
                        raise ValueError(f"Image task failed: {task_data.get('error')}")
                    time.sleep(10)
                if not image_url:
                    raise TimeoutError("Image generation timed out")
            except requests.exceptions.HTTPError as e:
                logging.error(f"Runway image request failed: {e.response.text}")
                logging.warning("Using fallback image due to Runway failure")
                image_url = "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?ixlib=rb-4.0.3&auto=format&fit=crop&w=720&h=1280&q=80"

            logging.info("Starting Runway video generation")
            video_payload = {
                "image": image_url,
                "text": script,
                "model": "gen4_image",
                "duration": 15,
                "ratio": "720:1280"
            }
            logging.info(f"Runway video payload: {json.dumps(video_payload)}")
            video_url = None
            try:
                video_response = requests.post("https://api.runwayml.com/v1/image_to_video", json=video_payload, headers=headers)
                video_response.raise_for_status()
                video_task_id = video_response.json().get("id")
                for _ in range(max_attempts):
                    poll_response = requests.get(f"https://api.runwayml.com/v1/tasks/{video_task_id}", headers=headers)
                    poll_response.raise_for_status()
                    task_data = poll_response.json()
                    logging.info(f"Runway video task status: {task_data.get('status')}")
                    if task_data.get("status") == "SUCCEEDED":
                        video_url = task_data.get("output", [{}])[0]
                        break
                    elif task_data.get("status") == "FAILED":
                        logging.error(f"Video task failed: {task_data.get('error')}")
                        raise ValueError(f"Video task failed: {task_data.get('error')}")
                    time.sleep(10)
                if not video_url:
                    raise TimeoutError("Video generation timed out")
            except requests.exceptions.HTTPError as e:
                logging.error(f"Runway video request failed: {e.response.text}")
                logging.warning("Using fallback video due to Runway failure")
                video_url = "https://example.com/fallback-finance-video.mp4"  # Replace with valid HTTPS video URL

            video_path = TEMP_DIR + "video.mp4"
            with open(video_path, "wb") as f:
                f.write(requests.get(video_url).content)

            # Step 5: Merge audio, video, and add captions
            logging.info("Merging video and audio")
            video_clip = VideoFileClip(video_path)
            audio_clip = AudioFileClip(audio_path).subclip(0, min(video_clip.duration, audio_clip.duration))
            caption_clip = TextClip("Trend: " + trend, fontsize=24, color='white').set_position('bottom').set_duration(video_clip.duration)
            merged_clip = CompositeVideoClip([video_clip.set_audio(audio_clip), caption_clip])
            merged_path = TEMP_DIR + "merged.mp4"
            merged_clip.write_videofile(merged_path, codec="libx264", audio_codec="aac")

            video_desc = f"Video based on script: {script}"
            video_score, video_feedback = verify_quality("video content", video_desc)
            logging.info(f"Video quality score: {video_score}, feedback: {video_feedback}")
            if video_score < 7:
                logging.warning(f"Low video quality ({score}/10), skipping post")
                continue

            if os.path.getsize(merged_path) > 10 * 1024 * 1024:
                raise ValueError("Video too large")

            # Step 6: Upload to Ayrshare
            logging.info("Uploading to Ayrshare")
            upload_url = "https://api.ayrshare.com/api/media/upload"
            upload_headers = {"Authorization": f"Bearer {AYRSHARE_API_KEY}"}
            files = {'file': open(merged_path, 'rb'), 'fileName': (None, 'trend_video.mp4'), 'description': (None, desc)}
            upload_response = requests.post(upload_url, headers=upload_headers, files=files)
            upload_response.raise_for_status()
            media_url = upload_response.json().get('url')

            # Step 7: Post with Ayrshare
            logging.info("Scheduling post")
            optimal_time = (datetime.utcnow() + timedelta(days=1)).replace(hour=16, minute=0, second=0, microsecond=0).isoformat() + 'Z'
            post_payload = {
                "post": desc,
                "mediaUrls": [media_url],
                "platforms": ["youtube", "tiktok", "instagram"],
                "youTubeOptions": {"title": title, "tags": [trend] + hashtags, "shorts": True},
                "hashTags": hashtags
            }
            ayrshare_url = "https://app.ayrshare.com/api/post"
            ayrshare_headers = {"Authorization": f"Bearer {AYRSHARE_API_KEY}", "Content-Type": "application/json"}
            post_response = requests.post(ayrshare_url, json=post_payload, headers=ayrshare_headers).json()

            for path in [audio_path, video_path, merged_path]:
                if os.path.exists(path):
                    os.remove(path)

            results.append({"trend": trend, "post_response": post_response})

        return jsonify({"status": "success", "results": results})
    except Exception as e:
        logging.error(f"Error in generate_content: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/analytics')
def get_analytics():
    try:
        logging.info("Fetching analytics")
        analytics_url = "https://app.ayrshare.com/api/analytics/post"
        response = requests.get(analytics_url, headers={"Authorization": f"Bearer {AYRSHARE_API_KEY}"}).json()
        insights_prompt = f"Analyze these analytics: {json.dumps(response)}. Suggest improvements for next videos in {NICHE} niche."
        insights_response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": insights_prompt}]
        )
        insights = insights_response.choices[0].message.content
        return jsonify({"analytics": response, "insights": insights})
    except Exception as e:
        logging.error(f"Error in analytics: {str(e)}")
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    logging.info("Starting Flask app")
    app.run(debug=True)
