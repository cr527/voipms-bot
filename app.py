import os
import re
import requests
import json
from datetime import datetime
from groq import Groq
from flask import Flask, request

app = Flask(__name__)

# --- Configuration from Environment Variables ---
# VoIP.ms Credentials
VOIPMS_USERNAME = os.environ.get("VOIPMS_USERNAME", "croberts84@gmail.com")
VOIPMS_PASSWORD = os.environ.get("VOIPMS_PASSWORD")

# OpenClaw Configuration
OPENCLAW_GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "https://api.openclaw.ai")
OPENCLAW_GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN")

# AI API Keys (Groq is now secondary/fallback if OpenClaw fails or is not configured)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Notion Configuration
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DB_ID = os.environ.get("NOTION_DB_ID", "34529f5f-5ec3-810f-9b93-f3892d6a3665")

# Bot Specifics
AUTHORIZED_NUMBER = os.environ.get("AUTHORIZED_NUMBER")
DID = "9728664569"

# --- Initialize Clients ---
groq_client = Groq(api_key=GROQ_API_KEY)

# --- Helper Functions ---
def send_sms(to, message):
    """Send an SMS, splitting long messages into 160-char chunks (max 3 texts)."""
    url = "https://voip.ms/api/v1/rest.php"
    # Split into chunks of 160 chars max, send at most 3
    chunks = []
    while message and len(chunks) < 3:
        chunks.append(message[:160])
        message = message[160:]
    for chunk in chunks:
        params = {
            "api_username": VOIPMS_USERNAME,
            "api_password": VOIPMS_PASSWORD,
            "method": "sendSMS",
            "did": DID,
            "dst": to,
            "message": chunk
        }
        response = requests.get(url, params=params)
        result = response.json()
        print(f"send_sms result: {result}")
    return result if chunks else None

def ask_groq(message):
    if not GROQ_API_KEY:
        return "Groq API key not configured."
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a helpful assistant responding via SMS. Keep responses concise and under 160 characters when possible."},
                {"role": "user", "content": message}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error calling Groq API: {e}")
        return "Error processing your request via Groq. Check logs."

def send_to_openclaw(message, sender_number):
    """Send message to OpenClaw via /v1/agent/run (shares main agent session + memory)."""
    print(f"Attempting to send message to OpenClaw: {message}")
    target_url = f"{OPENCLAW_GATEWAY_URL}/v1/agent/run"

    if not OPENCLAW_GATEWAY_TOKEN:
        print("OPENCLAW_GATEWAY_TOKEN not configured. Cannot send to OpenClaw.")
        return None

    headers = {
        "Authorization": f"Bearer {OPENCLAW_GATEWAY_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "message": f"[SMS from {sender_number}] {message}\n\n(Respond in 1-2 short sentences max. This is SMS — keep it under 300 characters total.)",
        "sessionKey": "main"
    }

    try:
        response = requests.post(target_url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        response_data = response.json()
        openclaw_reply = response_data.get("response", "No reply from OpenClaw.")
        # Truncate to 480 chars (3 SMS max) to prevent text floods
        if len(openclaw_reply) > 480:
            openclaw_reply = openclaw_reply[:477] + "..."
        print(f"Received reply from OpenClaw: {openclaw_reply}")
        return openclaw_reply
    except requests.exceptions.Timeout:
        print("OpenClaw request timed out.")
        return "OpenClaw is taking too long to respond. Try again later."
    except requests.exceptions.RequestException as e:
        print(f"Error sending to OpenClaw: {e}")
        return f"OpenClaw communication error. ({e})"
    except (json.JSONDecodeError, KeyError) as e:
        print(f"OpenClaw response parse error: {e} — raw: {response.text}")
        return "OpenClaw sent an unreadable response."

def notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

def add_task(task_name):
    if not NOTION_TOKEN or not NOTION_DB_ID:
        return {"error": "Notion not configured."}
    data = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": task_name}}]},
            "Status": {"select": {"name": "To Check Out"}}
        }
    }
    try:
        r = requests.post("https://api.notion.com/v1/pages", headers=notion_headers(), json=data)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"Error adding Notion task: {e}")
        return {"error": f"Failed to add Notion task: {e}"}

def add_reminder(task_name, due_date_str):
    if not NOTION_TOKEN or not NOTION_DB_ID:
        return {"error": "Notion not configured."}
    props = {
        "Name": {"title": [{"text": {"content": task_name}}]},
        "Status": {"select": {"name": "To Check Out"}},
        "Notes": {"rich_text": [{"text": {"content": "Reminder"}}]},
        "Type": {"select": {"name": "Idea"}},
    }
    if due_date_str:
        props["Added"] = {"date": {"start": due_date_str}}
    data = {"parent": {"database_id": NOTION_DB_ID}, "properties": props}
    try:
        r = requests.post("https://api.notion.com/v1/pages", headers=notion_headers(), json=data)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"Error adding Notion reminder: {e}")
        return {"error": f"Failed to add Notion reminder: {e}"}

def get_reminders():
    if not NOTION_TOKEN or not NOTION_DB_ID:
        return []
    data = {
        "filter": {
            "property": "Notes",
            "rich_text": {"contains": "Reminder"}
        },
        "sorts": [{"property": "Added", "direction": "ascending"}],
        "page_size": 10
    }
    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=notion_headers(),
            json=data
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        reminders = []
        for page in results:
            props = page.get("properties", {})
            title = props.get("Name", {}).get("title", [])
            name = title[0]["text"]["content"] if title else "Untitled"
            due = props.get("Added", {}).get("date")
            due_str = due["start"] if due else "No date"
            reminders.append(f"{name} ({due_str})")
        return reminders
    except requests.exceptions.RequestException as e:
        print(f"Error getting Notion reminders: {e}")
        return []

def parse_due_date(text):
    """Try to extract a date from natural language using Groq."""
    if not GROQ_API_KEY:
        print("Groq API key not configured for date parsing.")
        return None
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = f"Today is {today}. Extract the date and time from this text and return ONLY an ISO 8601 datetime string (YYYY-MM-DDTHH:MM:SS) or date (YYYY-MM-DD). If no date found, return NONE. Text: {text}"
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )
        result = response.choices[0].message.content.strip()
        if result == "NONE" or not re.match(r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$', result):
            return None
        return result
    except Exception as e:
        print(f"Error parsing date with Groq: {e}")
        return None

@app.route("/sms", methods=["GET", "POST"])
def receive_sms():
    print("=== INCOMING REQUEST ===")
    print(f"Method: {request.method}")
    print(f"Data: {request.get_data()}")
    print("========================")

    from_number = None
    message = None

    json_data = request.get_json(silent=True)
    if json_data:
        try:
            if "data" in json_data and "payload" in json_data["data"]:
                payload = json_data["data"]["payload"]
                from_number = payload.get("from", {}).get("phone_number")
                message = payload.get("text")
            elif json_data.get("event") == "sms":
                from_number = json_data.get("from_number")
                message = json_data.get("message")
            elif json_data.get("type") == "sms" or json_data.get("type") == "sms_mo":
                from_number = json_data.get("from")
                message = json_data.get("message")

            if not from_number and "from" in json_data:
                from_number = json_data.get("from")
            if not message and "message" in json_data:
                message = json_data.get("message")

        except Exception as e:
            print(f"JSON parse error: {e}")

    if not from_number:
        from_number = request.args.get("from") or request.form.get("from")
    if not message:
        message = request.args.get("message") or request.form.get("message")

    if not from_number or not message:
        print("Missing 'from' or 'message' parameters in request.")
        return "Missing params", 400

    clean_from = from_number.replace("-", "").replace(" ", "")
    if clean_from.startswith("+"):
        clean_from = clean_from[1:]
    if len(clean_from) == 11 and clean_from.startswith("1"):
        clean_from = clean_from[1:]

    clean_auth = ""
    if AUTHORIZED_NUMBER:
        clean_auth = AUTHORIZED_NUMBER.replace("-", "").replace(" ", "")
        if clean_auth.startswith("+"):
            clean_auth = clean_auth[1:]
        if len(clean_auth) == 11 and clean_auth.startswith("1"):
            clean_auth = clean_auth[1:]

    print(f"Cleaned from_number: {clean_from}, Authorized number: {clean_auth}")

    if clean_auth and clean_from != clean_auth:
        print(f"Unauthorized access attempt from {from_number}")
        return "Unauthorized", 403

    msg = message.strip()
    msg_lower = msg.lower()
    reply = ""

    if msg_lower.startswith("add task "):
        task_name = msg[9:].strip()
        add_task(task_name)
        reply = f"Task added to Notion: {task_name}"

    elif msg_lower.startswith("remind me "):
        reminder_text = msg[10:].strip()
        due_date = parse_due_date(reminder_text)
        task_name = re.sub(r'\b(at|on|by)\b.*$', '', reminder_text, flags=re.IGNORECASE).strip()
        if not task_name:
            task_name = reminder_text
        add_reminder(task_name, due_date)
        date_info = f" (due {due_date})" if due_date else ""
        reply = f"Reminder set in Notion: {task_name}{date_info}"

    elif msg_lower in ["reminders", "my reminders", "list reminders"]:
        items = get_reminders()
        if items:
            reply = "Notion Reminders:\n" + "\n".join(items[:5])
        else:
            reply = "No Notion reminders found."

    else:
        openclaw_reply = send_to_openclaw(msg, clean_from)
        if openclaw_reply:
            reply = openclaw_reply
        else:
            if GROQ_API_KEY:
                reply = ask_groq(msg)
            else:
                reply = "OpenClaw not reachable and Groq API key is missing. Cannot process request."

    print(f"Final Reply: {reply}")

    if reply and reply.strip() != "":
        send_sms(clean_from, reply)
    else:
        print("No reply to send via SMS.")

    return "OK", 200

@app.route("/")
def index():
    return "VoIP.ms SMS Bot is running.", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
