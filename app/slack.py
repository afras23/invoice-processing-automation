import requests
import os

def send_slack_message(text: str):
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    requests.post(webhook, json={"text": text})
