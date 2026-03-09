# bot.py
import telebot
from predictor import predict_match
from api_helpers import get_match_data

# Use environment variables (set in Render)
import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "⚽ Bot is running! Send a match ID.")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    try:
        match_id = int(message.text.strip())
        match_data = get_match_data(match_id)
        if not match_data:
            bot.reply_to(message, "❌ Match not found.")
            return

        # Simulate team strengths
        s_home = 9.24
        s_away = 6.81
        delta = s_home - s_away
        probs = predict_match(delta)

        result = "\n".join([f"{k}: {v:.2%}" for k, v in probs.items()])
        bot.reply_to(message, f"Prediction:\n{result}")

    except Exception as e:
        bot.reply_to(message, "⚠️ Error processing request.")
        print("Error:", str(e))

print("🚀 Bot is running...")
bot.infinity_polling()

import telebot
from config import TELEGRAM_BOT_TOKEN
from predictor import predict_match
from api_helpers import get_match_data

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Welcome to the Football Match Predictor Bot!\nSend me a match ID to get predictions.")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    try:
        match_id = int(message.text.strip())
        match = get_match_data(match_id)
        if not match:
            bot.reply_to(message, "Invalid match ID.")
            return

        home = match['teams']['home']['name']
        away = match['teams']['away']['name']

        # Simulate strength
        s_home = 9.24
        s_away = 6.81
        delta = s_home - s_away
        probs = predict_match(delta)

        response = f"Prediction for {home} vs {away}