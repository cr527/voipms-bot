from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from datetime import datetime
import time
import json
import requests

# --- Environment Variables --- #
# Render automatically provides environment variables you set.
# For local development, you might use python-dotenv or set them directly.
VOIPMS_SMS_DID = os.environ.get('VOIPMS_SMS_DID', 'your_did_here')
OPENCLAW_GATEWAY_URL = os.environ.get('OPENCLAW_GATEWAY_URL', 'https://api.openclaw.ai') # Default to public API
OPENCLAW_GATEWAY_TOKEN = os.environ.get('OPENCLAW_GATEWAY_TOKEN', 'your_token_here')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', 'your_groq_api_key_here')

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://192.168.4.57:8000"}}}) # Enable CORS for your local UI

# --- Helper Functions --- #
def send_to_openclaw(message_text, token=None, gateway_url=None):
    # Prioritize provided token and gateway_url, then environment variables
    final_token = token if token else OPENCLAW_GATEWAY_TOKEN
    final_gateway_url = gateway_url if gateway_url else OPENCLAW_GATEWAY_URL

    if not final_token or not final_gateway_url:
        print("OpenClaw Gateway URL or Token not set. Cannot send to OpenClaw.")
        return "Error: OpenClaw not configured."

    target_url = f"{final_gateway_url.rstrip('/')}/api/v1/sessions_send"
    headers = {
        "Authorization": f"Bearer {final_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "message": message_text,
        "agentId": "main" # Assuming the main agent should handle this
    }

    print(f"Sending to OpenClaw: {target_url}")
    try:
        response = requests.post(target_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        print(f"OpenClaw response status: {response.status_code}")
        print(f"OpenClaw response: {response.json()}")
        return response.json().get('message', 'OpenClaw response received.')
    except requests.exceptions.RequestException as e:
        print(f"Error sending to OpenClaw: {e}")
        return f"Error communicating with OpenClaw Gateway: {e}"


def ask_groq(prompt):
    # Groq API integration (fallback if OpenClaw is not used for some reason)
    groq_api_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "model": "mixtral-8x7b-32768"  # Or another suitable model
    }
    try:
        response = requests.post(groq_api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        print(f"Error asking Groq: {e}")
        return "Error communicating with AI."

def get_light_state_internal(light_name, api_type):
    # This function would query the state of a light. Implemented later.
    # For now, it returns a dummy state.
    return {"name": light_name, "state": "unknown", "bri": 0, "hue": 0, "sat": 0}

# --- Flask Routes --- #
@app.route('/sms', methods=['POST'])
def sms_reply():
    from_number = None
    message = None

    # Try to parse as JSON first
    json_data = request.get_json(silent=True)
    if json_data:
        print(f"Parsed JSON data: {json_data}")
        if "from" in json_data:
            from_number = json_data["from"]
        if "message" in json_data:
            message = json_data["message"]
        elif "data" in json_data and "payload" in json_data["data"]:
            payload = json_data["data"]["payload"]
            from_number = payload.get("from", {}).get("phone_number")
            message = payload.get("text")
        elif json_data.get("event") == "sms":
            from_number = json_data.get("from_number")
            message = json_data.get("message")
        elif json_data.get("type") == "sms" or json_data.get("type") == "sms_mo":
            from_number = json_data.get("from")
            message = json_data.get("message")

    # If not found in JSON, try form data or query parameters
    if not from_number:
        from_number = request.form.get("from")
    if not message:
        message = request.form.get("message")

    if not from_number:
        from_number = request.args.get("from")
    if not message:
        message = request.args.get("message")

    if not from_number or not message:
        print(f"Missing params: from_number={from_number}, message={message}")
        return jsonify({"status": "error", "message": "Missing params"}), 400

    message_lower = message.lower()
    response_text = ""

    print(f"Received SMS from {from_number}: {message}")

    if message_lower == "sexy":
        print("Executing sexy command...")
        # Define lights and actions for the "sexy" command
        # Dummy comment to force a Render redeploy - please ignore - Fix 2
        hue_lights = [
            {"name": "TV Room Lamp", "bri": 254, "hue": 0, "sat": 254}, # Red
            {"name": "Chris\' nightstand", "bri": 254, "hue": 0, "sat": 254}, # Red
            {"name": "Jana\'s nightstand", "bri": 254, "hue": 0, "sat": 254} # Red
        ]

        for light in hue_lights:
            # Construct the OpenClaw command for Hue lights
            command = f"openhue set light \"{light[\"name\"]}\" --on " \
                      f"--bri {light[\"bri\"]} --hue {light[\"hue\"]} --sat {light[\"sat\"]}"
            print(f"Sending to OpenClaw: {command}")
            oc_response = send_to_openclaw(command)
            print(f"OpenClaw response for {light[\"name\"]}: {oc_response}")
            time.sleep(1) # Delay to respect Hue rate limits

        response_text = "Executing sexy lighting sequence."
    else:
        # Fallback to OpenClaw for other commands
        oc_response = send_to_openclaw(f"SMS from {from_number}: {message}")
        response_text = oc_response if oc_response else f"Received your message: {message}"

    resp = jsonify({"status": "success", "message": response_text})
    # Add VoIP.ms specific headers if needed, for now just return JSON
    return resp

@app.route('/status', methods=['GET'])
def status_check():
    return jsonify({"status": "running", "message": "VoIP.ms Bot is operational"})


# Main entry point for local development/testing
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
