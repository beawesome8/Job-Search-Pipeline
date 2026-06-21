"""
get_telegram_chat_id.py

One-time helper: prints the chat_id for the most recent message
sent to this bot. Send any message to the bot in Telegram first,
then run this script to retrieve the chat_id needed for .env.

Usage:
    python src/get_telegram_chat_id.py
"""

import sys
import os
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TELEGRAM_BOT_TOKEN


def main():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    response = requests.get(url)
    data = response.json()

    if not data.get("result"):
        print("No messages found. Send any message to your bot in Telegram first, then run this again.")
        return

    chat_id = data["result"][-1]["message"]["chat"]["id"]
    print(f"Your chat_id is: {chat_id}")
    print("Add this to .env as TELEGRAM_CHAT_ID")


if __name__ == "__main__":
    main()
    