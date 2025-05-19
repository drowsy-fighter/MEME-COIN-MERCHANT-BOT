import os
import requests
import tweepy
from telegram import Bot
from telegram.ext import Updater, CommandHandler
from solana.rpc.api import Client
from datetime import datetime, timedelta

# Load env vars
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWITTER_BEARER = os.getenv("TWITTER_BEARER")

client = Client("https://api.mainnet-beta.solana.com")
bot = Bot(token=TELEGRAM_TOKEN)

# Setup Twitter
twitter = tweepy.Client(bearer_token=TWITTER_BEARER)

def scam_check(token):
    # Simulated scam check logic
    return {
        "honeypot": False,
        "rugpull_signals": False,
        "unlocked_liquidity": False,
        "renounced_ownership": True
    }

def get_recent_tokens():
    url = "https://api.dexscreener.com/latest/dex/pairs/solana"
    res = requests.get(url).json()
    tokens = []
    for pair in res["pairs"]:
        created = datetime.fromtimestamp(pair["pairCreatedAt"] / 1000)
        if datetime.utcnow() - created < timedelta(minutes=10):
            tokens.append(pair)
    return tokens

def check_coin_mentions(coin_name):
    query = f"{coin_name} lang:en"
    tweets = twitter.search_recent_tweets(query=query, max_results=10, tweet_fields=['public_metrics'])
    if not tweets.data:
        return 0
    return sum(t.public_metrics["like_count"] + t.public_metrics["retweet_count"] for t in tweets.data)

def evaluate_coin(token):
    if scam_check(token)['honeypot']:
        return None
    score = check_coin_mentions(token['baseToken']['name'])
    if score < 5:
        return None
    return {
        "name": token['baseToken']['name'],
        "score": score,
        "volume": token['volume']['h1'],
        "address": token['pairAddress']
    }

def alert(context):
    tokens = get_recent_tokens()
    for token in tokens:
        result = evaluate_coin(token)
        if result:
            bot.send_message(
                chat_id=CHAT_ID,
                text=f"🚀 {result['name']} launched!\n📈 Volume: {result['volume']}\n🐦 Twitter Score: {result['score']}\n🔗 Address: {result['address']}"
            )

# Telegram command to test bot
def start(update, context):
    update.message.reply_text("✅ Bot is live!")

def main():
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    
    job = updater.job_queue
    job.run_repeating(alert, interval=60, first=10)
    
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
