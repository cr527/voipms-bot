from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import time
import requests

# --- Environment Variables --- #
VOIPMS_SMS_DID = os.environ.get('VOIPMS_SMS_DID', 'your_did_here')
OPENCLAW_GATEWAY_URL = os.environ.get('OPENCLAW_GATEWAY_URL', 'https://api.openclaw.ai')
OPENCLAW_GATEWAY_TOKEN = os.environ.get('OPENCLAW_GATEWAY_TOKEN', 'your_token_here')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', 'your_groq_api_key_here')

app = Flask(__name__)
# Enable CORS for your local UI
CORS(app, resources={r"/*": {"origins": "http://192.168.4.57:8000"}})

# --- Helper Functions --- #
def send_to_openclaw(message_text, token=None, gateway_url=None):
    final_token = token if token else OPENCLAW_GATEWAY_TOKEN
    final_gateway_url = gateway_url if gateway_url else OPENCLAW_GATEWAY_URL

    if not final_token or not final_gateway_url:
        print("OpenClaw Gateway configuration missing.")
        return "Error: OpenClaw not configured."

    target_url = f"{final_gateway_url.rstrip('/')}/api/v1/sessions_send"
    headers = {
        "Authorization": f"Bearer {final_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "message": message_text,
        "agentId": "main" 
    }

    try:
        response = requests.post(target_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get('message', 'OpenClaw response received.')
    except requests.exceptions.RequestException as e:
        print(f"Error sending to OpenClaw: {e}")
        return f"Error communicating with OpenClaw: {e}"

def ask_groq(prompt):
    groq_api_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": "mixtral-8x7b-32768"
    }
    try:
        response = requests.post(groq_api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        print(f"Error asking Groq: {e}")
        return "Error communicating with AI."

# --- Flask Routes --- #
@app.route('/sms', methods=['POST'])
def sms_reply():
    from_number = None
    message = None

    json_data = request.get_json(silent=True)
    if json_data:
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

    # Fallback to form/query params
    if not from_number:
        from_number = request.form.get("from") or request.args.get("from")
    if not message:
        message = request.form.get("message") or request.args.get("message")

    if not from_number or not message:
        return jsonify({"status": "error", "message": "Missing params"}), 400

    print(f"Received SMS from {from_number}: {message}")
    message_lower = message.lower()

    if message_lower == "sexy":
        # Modified list: Only TV Room Lamp remains
        hue_lights = [
            {"name": "TV Room Lamp", "bri": 254, "hue": 0, "sat": 254}
        ]

        for light in hue_lights:
            command = (
                f"openhue set light \"{light['name']}\" --on "
                f"--bri {light['bri']} --hue {light['hue']} --sat {light['sat']}"
            )
            print(f"Sending command: {command}")
            send_to_openclaw(command)
            time.sleep(1) 

        response_text = "Executing sexy lighting sequence for TV Room Lamp."
    else:
        oc_response = send_to_openclaw(f"SMS from {from_number}: {message}")
        response_text = oc_response if oc_response else f"Received: {message}"

    return jsonify({"status": "success", "message": response_text})

@app.route('/status', methods=['GET'])
def status_check():
    return jsonify({"status": "running", "message": "VoIP.ms Bot is operational"})

if __name__ == '__main__':
    # Use port 5000 for local dev or Render default
    app.run(host='0.0.0.0', port=5000, debug=True)
