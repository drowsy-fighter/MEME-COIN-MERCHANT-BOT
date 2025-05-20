import os
import requests
import tweepy
from telegram import Bot
from telegram.ext import Updater, CommandHandler
from solana.rpc.api import Client
from solana.publickey import PublicKey
from datetime import datetime, timedelta

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWITTER_BEARER = os.getenv("TWITTER_BEARER")

client = Client("https://api.mainnet-beta.solana.com")
bot = Bot(token=TELEGRAM_TOKEN)

# Twitter setup
twitter = tweepy.Client(bearer_token=TWITTER_BEARER)

BIRDEYE_TOKEN_URL = "https://public-api.birdeye.so/public/token/"
BIRDEYE_HEADERS = {"X-API-KEY": os.getenv("BIRDEYE_API_KEY")}

def scam_check(token_address):
    try:
        response = requests.get(f"{BIRDEYE_TOKEN_URL}{token_address}", headers=BIRDEYE_HEADERS)
        data = response.json().get("data", {})
        
        # Simulated honeypot and renounce status (replace with real checks when available)
        honeypot = False
        renounced = data.get("isRenounced", True)
        unlocked_liquidity = not data.get("isLiquidityLocked", False)

        return {
            "honeypot": honeypot,
            "rugpull_signals": unlocked_liquidity or not renounced,
            "unlocked_liquidity": unlocked_liquidity,
            "renounced_ownership": renounced
        }
    except:
        return {"honeypot": True, "rugpull_signals": True, "unlocked_liquidity": True, "renounced_ownership": False}

def get_recent_tokens():
    url = "https://api.dexscreener.com/latest/dex/pairs/solana"
    res = requests.get(url).json()
    tokens = []
    for pair in res["pairs"]:
        created = datetime.fromtimestamp(pair["pairCreatedAt"] / 1000)
        if datetime.utcnow() - created < timedelta(minutes=10):
            if pair.get("baseToken", {}).get("website") or pair.get("baseToken", {}).get("twitter"):
                tokens.append(pair)
    return tokens

def check_coin_mentions(coin_name):
    query = f"{coin_name} lang:en"
    tweets = twitter.search_recent_tweets(query=query, max_results=10, tweet_fields=['public_metrics'])
    if not tweets.data:
        return 0
    return sum(t.public_metrics["like_count"] + t.public_metrics["retweet_count"] for t in tweets.data)

def get_dev_hold_percentage(token_address):
    # Gets token supply and top holders from Solana RPC for on-chain analysis
    try:
        token_supply = client.get_token_supply(PublicKey(token_address))
        total_supply = int(token_supply['result']['value']['amount'])

        # Replace with real holder list fetch
        top_wallets = [
            {"address": "dev_wallet_1", "amount": int(0.2 * total_supply)},
            {"address": "wallet_2", "amount": int(0.05 * total_supply)}
        ]

        top_holder_share = max(w["amount"] for w in top_wallets) / total_supply
        return top_holder_share
    except:
        return 1  # Assume bad if failure

def is_flat_chart(prices):
    if len(prices) < 5:
        return False
    diffs = [abs(prices[i+1] - prices[i]) for i in range(len(prices)-1)]
    return max(diffs) > 2 * sum(diffs)/len(diffs)

def evaluate_coin(token):
    if token.get("priceUsd") is None or float(token["priceUsd"]) <= 0:
        return None

    if float(token.get("fdv", 0)) < 25000:
        return None

    token_address = token['pairAddress']
    scam_data = scam_check(token_address)
    if scam_data['honeypot'] or scam_data['rugpull_signals']:
        return None

    dev_hold = get_dev_hold_percentage(token_address)
    if dev_hold > 0.25:
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
