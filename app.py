import os
import requests
import time
import json
import logging
from flask import Flask, jsonify, render_template, request
from openai import OpenAI
from elevenlabs import VoiceSettings, save
from elevenlabs.client import ElevenLabs
from pytrends.request import TrendReq
from dotenv import load_dotenv
from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()  # Load .env for local dev

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# API Keys and configs from env vars
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
RUNWAY_API_KEY = os.getenv('RUNWAY_API_KEY')
AYRSHARE_API_KEY = os.getenv('AYRSHARE_API_KEY')
NICHE = os.getenv('NICHE', 'tech')  # Niche for targeting trends
AFFILIATE_LINK = os.getenv('AFFILIATE_LINK', 'https://example.com/aff')  # Affiliate link

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize ElevenLabs client
elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY) if ELEVENLABS_API_KEY else None

# Temp file prefix for Heroku
TEMP_DIR = '/tmp/' if 'DYNO' in os.environ else ''

# Scheduler for automated runs (e.g., twice daily)
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: generate_content(num_trends=3), 'cron', hour='8,16')  # Run at 8 AM and 4 PM UTC
scheduler.start()

@app.route('/')
def home():
    return render_template('index.html')  # Simple UI dashboard

@app.route('/generate', methods=['GET', 'POST'])
def generate_content(num_trends=1):  # Allow multiple trends
    results = []
    try:
        # Step 1: Fetch and filter Trends by niche with fallback
        try:
            pytrends = TrendReq(hl='en-US', tz=360, timeout=(10,25), retries=2, backoff_factor=0.1)
            trends_data = pytrends.trending_searches(pn='united_states')
            if not trends_data.empty:
                trends = trends_data.iloc[:, 0].tolist()[:20]
                # Filter for tech-related trends
                tech_keywords = ['ai', 'tech', 'software', 'app', 'digital', 'cyber', 'data', 'cloud', 'automation', 'productivity']
                filtered_trends = []
                for trend in trends:
                    if any(keyword in trend.lower() for keyword in tech_keywords):
                        filtered_trends.append(trend)
                
                if not filtered_trends:
                    # Fallback to predefined trending topics
                    filtered_trends = [
                        "AI productivity tools 2024",
                        "ChatGPT coding tricks", 
                        "Cybersecurity tips",
                        "Tech startup ideas"
                    ]
            else:
                raise Exception("No trends returned")
        except Exception as e:
            logging.warning(f"PyTrends failed: {e}, using fallback trends")
            filtered_trends = [
                "AI productivity tools 2024",
                "ChatGPT coding tricks",
                "Cybersecurity tips", 
                "Software development tools",
                "Tech trends 2024"
            ]
        
        trends_to_use = filtered_trends[:num_trends]

        for trend in trends_to_use:
            logging.info(f"Processing trend: {trend}")

            # Step 2: Analyze Trend with enhanced prompt
            analysis_prompt = f"""
            Analyze '{trend}' in {NICHE} niche for short-form video. 
            Output JSON: "script" (15-30s with hook in first 3s, CTA, affiliate link: {AFFILIATE_LINK}), 
            "title" (SEO-optimized), "description" (with hashtags and link), "hashtags" (list of 5 trending).
            """
            analysis_response = openai_client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": analysis_prompt}],
                response_format={"type": "json_object"}
            )
            analysis_json = json.loads(analysis_response.choices[0].message.content)
            script = analysis_json.get('script', "Default script")
            title = analysis_json.get('title', "Trend Video")
            desc = analysis_json.get('description', "Based on trending topic") + f"\n{AFFILIATE_LINK}"
            hashtags = analysis_json.get('hashtags', [])

            # Step 3: Generate Voiceover
           from elevenlabs.client import ElevenLabs
           from elevenlabs import VoiceSettings  # Keep if using, but it's optional in v1.x

           # In generate_content (Step 3):
          client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

          audio_stream = client.text_to_speech.convert(
           text=script,
           voice_id="21m00Tcm4TlvDq8ikWAM",  # Use 'Rachel' ID from ElevenLabs dashboard (confirm yours)
           model_id="eleven_turbo_v2",
           voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75, style=0.0, use_speaker_boost=True),
           output_format="mp3_44100_128"  # Or your preferred format
  )

            audio_path = TEMP_DIR + "voiceover.mp3"
            with open(audio_path, "wb") as f:
            for chunk in audio_stream:
            if chunk:
            f.write(chunk)           

            # Step 4: Generate Image then Video with Runway
            headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json", "X-Runway-Version": "2024-11-06"}

            # 4.1: Text-to-Image
            image_payload = {"promptText": script, "model": "gen4_image", "ratio": "9:16"}
            image_response = requests.post("https://api.dev.runwayml.com/v1/text_to_image", json=image_payload, headers=headers)
            image_response.raise_for_status()
            image_task_id = image_response.json().get("id")
            max_attempts = 60
            image_url = None
            for _ in range(max_attempts):
                poll_response = requests.get(f"https://api.dev.runwayml.com/v1/tasks/{image_task_id}", headers=headers)
                poll_response.raise_for_status()
                task_data = poll_response.json()
                if task_data.get("status") == "SUCCEEDED":
                    image_url = task_data.get("output", [{}])[0]
                    break
                elif task_data.get("status") == "FAILED":
                    raise ValueError(f"Image task failed: {task_data.get('failure', {}).get('reason', 'Unknown error')}")
                time.sleep(10)
            if not image_url:
                raise TimeoutError("Image generation timed out")

            # 4.2: Image-to-Video
            video_payload = {"promptImage": image_url, "promptText": script, "model": "gen3a_turbo", "duration": 15, "ratio": "9:16"}
            video_response = requests.post("https://api.dev.runwayml.com/v1/image_to_video", json=video_payload, headers=headers)
            video_response.raise_for_status()
            video_task_id = video_response.json().get("id")
            video_url = None
            for _ in range(max_attempts):
                poll_response = requests.get(f"https://api.dev.runwayml.com/v1/tasks/{video_task_id}", headers=headers)
                poll_response.raise_for_status()
                task_data = poll_response.json()
                if task_data.get("status") == "SUCCEEDED":
                    video_url = task_data.get("output", [{}])[0]
                    break
                elif task_data.get("status") == "FAILED":
                    raise ValueError(f"Video task failed: {task_data.get('failure', {}).get('reason', 'Unknown error')}")
                time.sleep(10)
            if not video_url:
                raise TimeoutError("Video generation timed out")

            # Download video
            video_path = TEMP_DIR + "video.mp4"
            with open(video_path, "wb") as f:
                f.write(requests.get(video_url).content)

            # Step 5: Merge audio, video, and add captions
            video_clip = VideoFileClip(video_path)
            
            # Handle audio if available
            if audio_path and os.path.exists(audio_path):
                audio_clip = AudioFileClip(audio_path).subclip(0, min(video_clip.duration, AudioFileClip(audio_path).duration))
                video_clip = video_clip.set_audio(audio_clip)
            
            caption_clip = TextClip("Trend: " + trend, fontsize=24, color='white').set_position('bottom').set_duration(video_clip.duration)
            merged_clip = CompositeVideoClip([video_clip, caption_clip])
            merged_path = TEMP_DIR + "merged.mp4"
            merged_clip.write_videofile(merged_path, codec="libx264", audio_codec="aac")

            # File size check
            if os.path.getsize(merged_path) > 10 * 1024 * 1024:
                raise ValueError("Video too large")

            # Step 6: Upload to Ayrshare
            upload_url = "https://api.ayrshare.com/api/media/upload"
            upload_headers = {"Authorization": f"Bearer {AYRSHARE_API_KEY}"}
            files = {'file': open(merged_path, 'rb'), 'fileName': (None, 'trend_video.mp4'), 'description': (None, desc)}
            upload_response = requests.post(upload_url, headers=upload_headers, files=files)
            upload_response.raise_for_status()
            media_url = upload_response.json().get('url')

            # Step 7: Post with Ayrshare
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

            # Cleanup
            cleanup_paths = [video_path, merged_path]
            if audio_path:
                cleanup_paths.append(audio_path)
            
            for path in cleanup_paths:
                if os.path.exists(path):
                    os.remove(path)

            results.append({"trend": trend, "post_response": post_response})

        return jsonify({"status": "success", "results": results})
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/analytics')
def get_analytics():
    try:
        analytics_url = "https://app.ayrshare.com/api/analytics/post"
        response = requests.get(analytics_url, headers={"Authorization": f"Bearer {AYRSHARE_API_KEY}"}).json()
        # Optional: Analyze with OpenAI for insights
        insights_prompt = f"Analyze these analytics: {json.dumps(response)}. Suggest improvements for next videos."
        insights_response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": insights_prompt}]
        )
        insights = insights_response.choices[0].message.content
        return jsonify({"analytics": response, "insights": insights})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/status')
def status():
    """Simple status endpoint"""
    return jsonify({
        "status": "operational",
        "system": "AI Content Automation",
        "version": "2.0.0",
        "features": ["trend_detection", "video_generation", "auto_posting", "analytics"]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

