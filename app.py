import os
import re
import requests
from datetime import datetime
from groq import Groq
from flask import Flask, request

app = Flask(__name__)

VOIPMS_USERNAME = os.environ.get("VOIPMS_USERNAME", "croberts84@gmail.com")
VOIPMS_PASSWORD = os.environ.get("VOIPMS_PASSWORD")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
AUTHORIZED_NUMBER = os.environ.get("AUTHORIZED_NUMBER")
DID = "9728664569"
NOTION_DB_ID = "0c61f35c-0b97-4cfe-b619-736f972a0e3d"

groq_client = Groq(api_key=GROQ_API_KEY)

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
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a helpful assistant responding via SMS. Keep responses concise and under 160 characters when possible."},
            {"role": "user", "content": message}
        ]
    )
    return response.choices[0].message.content

def notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

def add_task(task_name):
    data = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Task": {"title": [{"text": {"content": task_name}}]},
            "Status": {"select": {"name": "Not Started"}}
        }
    }
    r = requests.post("https://api.notion.com/v1/pages", headers=notion_headers(), json=data)
    return r.json()

def add_reminder(task_name, due_date_str):
    props = {
        "Task": {"title": [{"text": {"content": task_name}}]},
        "Status": {"select": {"name": "Not Started"}},
        "Notes": {"rich_text": [{"text": {"content": "Reminder"}}]}
    }
    if due_date_str:
        props["Due Date"] = {"date": {"start": due_date_str}}
    data = {"parent": {"database_id": NOTION_DB_ID}, "properties": props}
    r = requests.post("https://api.notion.com/v1/pages", headers=notion_headers(), json=data)
    return r.json()

def get_reminders():
    data = {
        "filter": {
            "property": "Notes",
            "rich_text": {"contains": "Reminder"}
        },
        "sorts": [{"property": "Due Date", "direction": "ascending"}],
        "page_size": 10
    }
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
        headers=notion_headers(),
        json=data
    )
    results = r.json().get("results", [])
    reminders = []
    for page in results:
        props = page.get("properties", {})
        title = props.get("Task", {}).get("title", [])
        name = title[0]["text"]["content"] if title else "Untitled"
        due = props.get("Due Date", {}).get("date")
        due_str = due["start"] if due else "No date"
        reminders.append(f"{name} ({due_str})")
    return reminders

def parse_due_date(text):
    """Try to extract a date from natural language using Groq."""
    today = datetime.now().strftime("%Y-%m-%d")
    prompt = f"Today is {today}. Extract the date and time from this text and return ONLY an ISO 8601 datetime string (YYYY-MM-DDTHH:MM:SS) or date (YYYY-MM-DD). If no date found, return NONE. Text: {text}"
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    )
    result = response.choices[0].message.content.strip()
    if result == "NONE" or not re.match(r'\d{4}-\d{2}-\d{2}', result):
        return None
    return result

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
            payload = json_data.get("data", {}).get("payload", {})
            from_number = payload.get("from", {}).get("phone_number")
            message = payload.get("text")
        except Exception as e:
            print(f"JSON parse error: {e}")

    if not from_number:
        from_number = request.args.get("from") or request.form.get("from")
    if not message:
        message = request.args.get("message") or request.form.get("message")

    if not from_number or not message:
        return "Missing params", 400

    clean_from = from_number.lstrip("+")
    if clean_from.startswith("1") and len(clean_from) == 11:
        clean_from = clean_from[1:]
    clean_auth = AUTHORIZED_NUMBER.replace("-", "").replace(" ", "")[-10:] if AUTHORIZED_NUMBER else ""

    if clean_auth and clean_from != clean_auth:
        return "Unauthorized", 403

    msg = message.strip()
    msg_lower = msg.lower()

    # Command: add task
    if msg_lower.startswith("add task "):
        task_name = msg[9:].strip()
        add_task(task_name)
        reply = f"Task added: {task_name}"

    # Command: remind me
    elif msg_lower.startswith("remind me "):
        reminder_text = msg[10:].strip()
        due_date = parse_due_date(reminder_text)
        # Strip the date portion from the task name
        task_name = re.sub(r'\b(at|on|by)\b.*', '', reminder_text, flags=re.IGNORECASE).strip()
        add_reminder(task_name or reminder_text, due_date)
        date_info = f" at {due_date}" if due_date else ""
        reply = f"Reminder set: {task_name or reminder_text}{date_info}"

    # Command: reminders
    elif msg_lower in ["reminders", "my reminders", "list reminders"]:
        items = get_reminders()
        if items:
            reply = "Reminders:\n" + "\n".join(items[:5])
        else:
            reply = "No reminders found."

    # Fallback: ask Groq
    else:
        reply = ask_groq(msg)

    print(f"Reply: {reply}")
    send_sms(clean_from, reply)
    return "OK", 200

@app.route("/")
def index():
    return "VoIP.ms SMS Bot is running.", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
