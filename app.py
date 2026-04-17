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

client = OpenAI(api_key=OPENAI_API_KEY)

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

def ask_openai(message):
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
    # Log everything for debugging
    print("=== INCOMING REQUEST ===")
    print(f"Method: {request.method}")
    print(f"Args: {dict(request.args)}")
    print(f"Form: {dict(request.form)}")
    print(f"Data: {request.get_data()}")
    print("========================")

    # Try all possible field name variations VoIP.ms might use
    from_number = (
        request.args.get("from") or
        request.args.get("FROM") or
        request.form.get("from") or
        request.form.get("FROM")
    )
    message = (
        request.args.get("message") or
        request.args.get("MESSAGE") or
        request.form.get("message") or
        request.form.get("MESSAGE")
    )

    print(f"from_number={from_number}, message={message}")

    if not from_number or not message:
        print("ERROR: Missing from_number or message")
        return "Missing params", 400

    # Strip country code if present
    clean_from = from_number.lstrip("+").replace("1", "", 1).replace("-", "").replace(" ", "")
    if len(clean_from) > 10:
        clean_from = clean_from[-10:]
    clean_auth = AUTHORIZED_NUMBER.replace("-", "").replace(" ", "")[-10:] if AUTHORIZED_NUMBER else ""

    print(f"clean_from={clean_from}, clean_auth={clean_auth}")

    if clean_auth and clean_from != clean_auth:
        print(f"UNAUTHORIZED: {clean_from} != {clean_auth}")
        return "Unauthorized", 403

    reply = ask_openai(message)
    print(f"Reply: {reply}")

    send_sms(clean_from, reply)
    return "OK", 200

@app.route("/")
def index():
    return "VoIP.ms SMS Bot is running.", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
