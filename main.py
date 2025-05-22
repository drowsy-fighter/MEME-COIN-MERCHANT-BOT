import os
import time
import requests
import logging
from datetime import datetime, timedelta
from statistics import stdev
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, JobQueue, CallbackContext
from requests.adapters import HTTPAdapter, Retry
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Constants
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY")

DEX_URL = "https://api.dexscreener.com/latest/dex/pairs/solana"
BIRDEYE_TOKEN_URL = "https://public-api.birdeye.so/public/token/"
BIRDEYE_HISTORY_URL = "https://public-api.birdeye.so/public/price/history_token"

# Telegram bot and logging
bot = Bot(token=TELEGRAM_TOKEN)
logging.basicConfig(level=logging.INFO)

# API session with retry logic
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

# In-memory cache to reduce Birdeye API overuse
api_cache = {}

def get_recent_sol_pairs():
    try:
        res = session.get(DEX_URL).json()
        recent = []
        for pair in res.get("pairs", []):
            created = datetime.fromtimestamp(pair["pairCreatedAt"] / 1000)
            token = pair.get("baseToken", {})
            if datetime.utcnow() - created < timedelta(minutes=10):
                if token.get("website") or token.get("twitter"):
                    recent.append(pair)
        return recent
    except Exception as e:
        logging.error(f"Error fetching Dexscreener data: {e}")
        return []

def check_liquidity_and_ownership(token_address):
    if token_address in api_cache:
        return api_cache[token_address]["locked"], api_cache[token_address]["renounced"]

    headers = {"X-API-KEY": BIRDEYE_API_KEY}
    try:
        res = session.get(f"{BIRDEYE_TOKEN_URL}{token_address}", headers=headers)
        data = res.json().get("data", {})
        locked = data.get("isLiquidityLocked", False)
        renounced = data.get("isRenounced", True)
        # Cache result
        api_cache[token_address] = {"locked": locked, "renounced": renounced}
        return locked, renounced
    except Exception as e:
        logging.warning(f"Birdeye liquidity/ownership error for {token_address}: {e}")
        return False, False

def get_chart(token_address):
    if f"{token_address}_chart" in api_cache:
        return api_cache[f"{token_address}_chart"]

    headers = {"X-API-KEY": BIRDEYE_API_KEY}
    params = {"address": token_address, "interval": "1m"}
    try:
        res = session.get(BIRDEYE_HISTORY_URL, params=params, headers=headers)
        prices = [p["value"] for p in res.json().get("data", {}).get("items", []) if p.get("value")]
        # Cache it
        api_cache[f"{token_address}_chart"] = prices
        return prices
    except Exception as e:
        logging.warning(f"Birdeye chart error for {token_address}: {e}")
        return []

def analyze_chart(prices):
    if len(prices) < 5:
        return "⚠️ Not enough data"
    try:
        std_dev = stdev(prices)
        if std_dev < 0.001:
            return "⚠️ Too Flat"
        return "✅ Organic"
    except:
        return "⚠️ Error Analyzing"

def evaluate_coin(pair):
    base = pair.get("baseToken", {})
    token_address = base.get("address")
    if not token_address:
        return None

    # Volume Filter
    if pair.get("volume", {}).get("h1", 0) < 5000:
        return None

    # Liquidity Lock + Ownership Renounce Check
    locked, renounced = check_liquidity_and_ownership(token_address)
    if not (locked and renounced):
        return None

    # Chart Analysis
    prices = get_chart(token_address)
    chart_result = analyze_chart(prices)
    if chart_result != "✅ Organic":
        return None

    return {
        "name": base.get("name", "Unknown"),
        "address": token_address,
        "chart": chart_result,
        "volume": pair.get("volume", {}).get("h1", 0),
        "social": base.get("twitter") or base.get("website") or "N/A"
    }

def send_coin_alert(result):
    try:
        bot.send_message(
            chat_id=CHAT_ID,
            text=(
                f"🚀 *{result['name']}* just launched on Solana!\n\n"
                f"📊 *Volume (1h):* ${int(result['volume']):,}\n"
                f"📈 *Chart:* {result['chart']}\n"
                f"🌐 *Social:* {result['social']}\n"
                f"`{result['address']}`"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Telegram send error: {e}")

def alert(context: CallbackContext):
    pairs = get_recent_sol_pairs()
    for pair in pairs:
        result = evaluate_coin(pair)
        if result:
            send_coin_alert(result)

def start(update: Update, context: CallbackContext):
    update.message.reply_text("✅ Bot is live and scanning fresh Solana coins!")

def top(update: Update, context: CallbackContext):
    coins = get_recent_sol_pairs()
    results = [evaluate_coin(p) for p in coins]
    good = [r for r in results if r]
    if not good:
        update.message.reply_text("😕 No high-quality tokens found right now.")
    else:
        for r in good[:5]:  # limit results
            send_coin_alert(r)

def main():
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("top", top))

    # Job every minute
    jq: JobQueue = updater.job_queue
    jq.run_repeating(alert, interval=60, first=10)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
