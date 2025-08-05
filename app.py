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
from runwayml import RunwayML  # Import Runway SDK

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

logging.info("Initializing Runway client...")
try:
    runway_client = RunwayML(api_key=RUNWAY_API_KEY)
except Exception as e:
    logging.error(f"Failed to initialize Runway client: {str(e)}")
    raise

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
                script = analysis_json.get('script', "Default script")[:2048]  # Trim to 2048 chars
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
                voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel's ID; verify in ElevenLabs dashboard
                model_id="eleven_turbo_v2",
                voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75, style=0.0, use_speaker_boost=True),
                output_format="mp3_44100_128"
            )
            audio_path = TEMP_DIR + "voiceover.mp3"
            with open(audio_path, "wb") as f:
                for chunk in audio_stream:
                    if chunk:
                        f.write(chunk)

            # Step 4: Generate Image then Video with Runway using SDK
            logging.info("Starting Runway image generation")
            try:
                image_task = runway_client.textToImage.create(
                    model='gen4_image',
                    promptText=script,
                    ratio='720:1280'
                )
                image_task_id = image_task.id
                image_task_output = image_task.waitForTaskOutput()
                image_url = image_task_output.output[0]
            except Exception as e:
                logging.error(f"Runway image generation failed: {str(e)}")
                logging.warning("Using fallback image due to Runway failure")
                image_url = "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?ixlib=rb-4.0.3&auto=format&fit=crop&w=720&h=1280&q=80"  # Valid HTTPS image

            logging.info("Starting Runway video generation")
            try:
                video_task = runway_client.imageToVideo.create(
                    image=image_url,
                    text=script,
                    model='gen4_image',
                    duration=15,
                    ratio='720:1280'
                )
                video_task_id = video_task.id
                video_task_output = video_task.waitForTaskOutput()
                video_url = video_task_output.output[0]
            except Exception as e:
                logging.error(f"Runway video generation failed: {str(e)}")
                raise

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
                logging.warning(f"Low video quality ({video_score}/10), skipping post")
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
