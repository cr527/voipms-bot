import os
import requests
from groq import Groq
from flask import Flask, request

app = Flask(__name__)

VOIPMS_USERNAME = os.environ.get("VOIPMS_USERNAME", "croberts84@gmail.com")
VOIPMS_PASSWORD = os.environ.get("VOIPMS_PASSWORD")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
AUTHORIZED_NUMBER = os.environ.get("AUTHORIZED_NUMBER")
DID = "9728664569"

client = Groq(api_key=GROQ_API_KEY)

def send_sms(to, message):
    url = "https://voip.ms/api/v1/rest.php"
    params = {
        "api_username": VOIPMS_USERNAME,
        "api_password": VOIPMS_PASSWORD,
        "method": "sendSMS",
        "did": DID,
        "dst": to,
        "message": message[:160]
    }
    response = requests.get(url, params=params)
    result = response.json()
    print(f"send_sms result: {result}")
    return result

def ask_groq(message):
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a helpful assistant responding via SMS. Keep responses concise and under 160 characters when possible."},
            {"role": "user", "content": message}
        ]
    )
    return response.choices[0].message.content

@app.route("/sms", methods=["GET", "POST"])
def receive_sms():
    print("=== INCOMING REQUEST ===")
    print(f"Method: {request.method}")
    print(f"Args: {dict(request.args)}")
    print(f"Form: {dict(request.form)}")
    print(f"Data: {request.get_data()}")
    print("========================")

    from_number = None
    message = None

    # Try JSON body first (VoIP.ms webhook format)
    json_data = request.get_json(silent=True)
    if json_data:
        try:
            payload = json_data.get("data", {}).get("payload", {})
            from_number = payload.get("from", {}).get("phone_number")
            message = payload.get("text")
        except Exception as e:
            print(f"JSON parse error: {e}")

    # Fall back to query params / form data
    if not from_number:
        from_number = request.args.get("from") or request.form.get("from")
    if not message:
        message = request.args.get("message") or request.form.get("message")

    print(f"from_number={from_number}, message={message}")

    if not from_number or not message:
        print("ERROR: Missing from_number or message")
        return "Missing params", 400

    # Normalize to 10 digits
    clean_from = from_number.lstrip("+")
    if clean_from.startswith("1") and len(clean_from) == 11:
        clean_from = clean_from[1:]
    clean_auth = AUTHORIZED_NUMBER.replace("-", "").replace(" ", "")[-10:] if AUTHORIZED_NUMBER else ""

    print(f"clean_from={clean_from}, clean_auth={clean_auth}")

    if clean_auth and clean_from != clean_auth:
        print(f"UNAUTHORIZED: {clean_from} != {clean_auth}")
        return "Unauthorized", 403

    reply = ask_groq(message)
    print(f"Reply: {reply}")

    send_sms(clean_from, reply)
    return "OK", 200

@app.route("/")
def index():
    return "VoIP.ms SMS Bot is running.", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
