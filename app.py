import os
import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)

VOIPMS_USERNAME = os.environ.get("VOIPMS_USERNAME", "croberts84@gmail.com")
VOIPMS_PASSWORD = os.environ.get("VOIPMS_PASSWORD")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
AUTHORIZED_NUMBER = os.environ.get("AUTHORIZED_NUMBER")
DID = "9728664569"

client = OpenAI(
    api_key=OPENAI_API_KEY
)

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
    return response.json()

def ask_perplexity(message):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant responding via SMS. Keep responses concise and under 160 characters when possible."
            },
            {
                "role": "user",
                "content": message
            }
        ]
    )
    return response.choices[0].message.content

@app.route("/sms", methods=["GET", "POST"])
def receive_sms():
    from_number = request.args.get("from") or request.form.get("from")
    message = request.args.get("message") or request.form.get("message")

    if not from_number or not message:
        return "Missing params", 400

    # Strip country code if present
    clean_from = from_number.lstrip("+1").replace("-", "").replace(" ", "")
    clean_auth = AUTHORIZED_NUMBER.lstrip("+1").replace("-", "").replace(" ", "") if AUTHORIZED_NUMBER else ""

    if clean_auth and clean_from != clean_auth:
        return "Unauthorized", 403

    # Get AI response
    reply = ask_perplexity(message)

    # Send reply
    send_sms(clean_from, reply)

    return "OK", 200

@app.route("/")
def index():
    return "VoIP.ms SMS Bot is running.", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
