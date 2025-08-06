from flask import Flask, render_template, request, redirect, url_for, send_file
import openai
import requests
import os
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip
from gtts import gTTS
from io import BytesIO

app = Flask(__name__)

# Set API keys from environment variables
openai.api_key = os.getenv("OPENAI_API_KEY")
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

@app.route('/')
def index():
    return redirect(url_for('generate_page'))

@app.route('/generate', methods=['GET'])
def generate_page():
    return render_template('generate.html')

@app.route('/generate_image', methods=['POST'])
def generate_image():
    prompt = request.form.get('prompt')
    if not prompt:
        return "No prompt provided.", 400

    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "prompt": prompt,
        "width": 1024,
        "height": 768
    }

    response = requests.post("https://api.runwayml.com/v1/generate/image", json=data, headers=headers)

    if response.status_code != 200:
        return f"Runway API error: {response.text}", 500

    image_url = response.json().get("image_url")
    return f"<h2>Generated Image</h2><img src='{image_url}' width='512'><br><a href='/generate'>Go Back</a>"

@app.route('/generate_video', methods=['POST'])
def generate_video():
    topic = request.form.get('topic')
    if not topic:
        return "No topic provided.", 400

    # Step 1: Generate script using OpenAI
    script_prompt = f"Write a compelling YouTube short script on: {topic}"
    completion = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": script_prompt}]
    )
    script = completion.choices[0].message['content']

    # Step 2: Generate voiceover with ElevenLabs
    voice_url = f"https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "text": script,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }

    audio_response = requests.post(voice_url, json=data, headers=headers)
    if audio_response.status_code != 200:
        return f"Voice generation failed: {audio_response.text}", 500

    audio_path = "static/audio.mp3"
    with open(audio_path, "wb") as f:
        f.write(audio_response.content)

    # Step 3: Generate image (placeholder for background video)
    img_response = requests.post("https://api.runwayml.com/v1/generate/image",
                                 json={"prompt": topic, "width": 1024, "height": 768},
                                 headers={"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json"})
    if img_response.status_code != 200:
        return f"Image generation failed: {img_response.text}", 500

    image_url = img_response.json().get("image_url")
    image_data = requests.get(image_url).content
    image_path = "static/frame.jpg"
    with open(image_path, 'wb') as img_file:
        img_file.write(image_data)

    # Step 4: Create video with MoviePy
    from moviepy.editor import ImageClip
    image_clip = ImageClip(image_path).set_duration(10)
    audio_clip = AudioFileClip(audio_path)
    video = image_clip.set_audio(audio_clip)
    video_path = "static/final_video.mp4"
    video.write_videofile(video_path, fps=24)

    return f"<h2>Generated Video</h2><video controls width='512'><source src='/{video_path}' type='video/mp4'></video><br><a href='/generate'>Go Back</a>"

if __name__ == '__main__':
    app.run(debug=True)