import os
import uuid
from flask import Flask, request, jsonify, send_file, render_template
from flask_apscheduler import APScheduler
from runwayml import RunwayML, TaskFailedError, TaskTimeoutError
from elevenlabs import Voice, VoiceSettings, generate, save
from moviepy.editor import AudioFileClip, VideoFileClip, CompositeVideoClip

app = Flask(__name__)

# Set up RunwayML with API key from environment variable
client = RunwayML(api_key=os.getenv("RUNWAYML_API_SECRET"))

# ElevenLabs API Key
ELEVEN_API_KEY = os.getenv("ELEVENLABS_API_KEY")

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

def cleanup_file(filepath):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        print(f"Cleanup error: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate-image', methods=['POST'])
def generate_image():
    data = request.json
    prompt = data.get('prompt', '')

    try:
        image_task = client.text_to_image.create(
            model='gen4_image',
            prompt_text=prompt,
            ratio='16:9'
        )
        output = image_task.wait_for_task_output(timeout=300)
        return jsonify({'image_url': output.output[0]})
    except TaskFailedError as e:
        return jsonify({'error': f'Task failed: {str(e)}'}), 500
    except TaskTimeoutError as e:
        return jsonify({'error': 'Task timed out'}), 504

@app.route('/generate-video', methods=['POST'])
def generate_video():
    data = request.json
    image_url = data.get('image_url')
    prompt = data.get('prompt', '')

    try:
        video_task = client.image_to_video.create(
            model='gen2',
            image_url=image_url,
            prompt_text=prompt
        )
        output = video_task.wait_for_task_output(timeout=300)
        return jsonify({'video_url': output.output[0]})
    except TaskFailedError as e:
        return jsonify({'error': f'Task failed: {str(e)}'}), 500
    except TaskTimeoutError as e:
        return jsonify({'error': 'Task timed out'}), 504

@app.route('/generate-audio', methods=['POST'])
def generate_audio():
    data = request.json
    text = data.get('text', '')

    audio = generate(
        text=text,
        voice=Voice(
            voice_id="EXAVITQu4vr4xnSDxMaL",
            settings=VoiceSettings(stability=0.5, similarity_boost=0.75)
        ),
        api_key=ELEVEN_API_KEY
    )

    filename = f"{uuid.uuid4()}.mp3"
    save(audio, filename)

    scheduler.add_job(id=filename, func=lambda: cleanup_file(filename), trigger='date', run_date=None, seconds=300)

    return send_file(filename, as_attachment=True)

@app.route('/merge', methods=['POST'])
def merge_audio_video():
    data = request.json
    video_path = data.get('video_path')
    audio_path = data.get('audio_path')

    try:
        video = VideoFileClip(video_path)
        audio = AudioFileClip(audio_path)
        video = video.set_audio(audio)

        output_path = f"merged_{uuid.uuid4()}.mp4"
        video.write_videofile(output_path, codec='libx264', audio_codec='aac')

        scheduler.add_job(id=output_path, func=lambda: cleanup_file(output_path), trigger='date', run_date=None, seconds=300)

        return send_file(output_path, as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)