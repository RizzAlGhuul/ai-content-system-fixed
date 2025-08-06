import os
import requests
import httpx

RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY")

HEADERS = {
    "Authorization": f"Bearer {RUNWAY_API_KEY}",
    "Content-Type": "application/json"
}

def generate_runway_image(prompt):
    try:
        response = httpx.post(
            "https://api.runwayml.com/v1/text_to_image",
            headers=HEADERS,
            json={
                "prompt": prompt,
                "width": 512,
                "height": 512,
                "num_inference_steps": 25,
                "guidance_scale": 7.5
            },
            timeout=60
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        print(f"Runway image fallback: {exc.response.status_code} Client Error: {exc.response.text}")
        return None

def generate_runway_video(prompt):
    try:
        response = httpx.post(
            "https://api.runwayml.com/v1/video",
            headers=HEADERS,
            json={
                "prompt": prompt,
                "width": 512,
                "height": 512,
                "num_inference_steps": 30,
                "num_frames": 16,
                "guidance_scale": 10
            },
            timeout=120
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        print(f"Runway video fallback: {exc.response.status_code} Client Error: {exc.response.text}")
        return None

# You can then replace your usage logic with:

prompt_text = "A futuristic city skyline at dusk"
image_result = generate_runway_image(prompt_text)
video_result = generate_runway_video(prompt_text)