from flask import Flask, render_template, request, jsonify
import os
import httpx
import logging

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/generate", methods=["GET"])
def generate():
    try:
        logging.info("Starting Runway image generation")
        headers = {
            "Authorization": f"Bearer {os.getenv('RUNWAY_API_KEY')}",
            "Content-Type": "application/json"
        }
        payload = {
            "prompt": "a futuristic city with flying cars",
            "width": 1024,
            "height": 768
        }
        response = httpx.post("https://api.runwayml.com/v2/generate", headers=headers, json=payload)
        response.raise_for_status()
        image_data = response.json()
        logging.info("Runway image generation successful")
        return jsonify(image_data)
    except httpx.HTTPStatusError as e:
        logging.warning(f"Runway fallback: {e.response.status_code} Client Error: {e.response.text}")
        return jsonify({"error": "Runway generation failed"}), 500
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": "Unexpected server error"}), 500

if __name__ == "__main__":
    app.run(debug=True)