import os
import asyncio
import logging
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import uvicorn
import requests
from datetime import datetime
import random

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyCXy4mUNWEllCMKRkJMqf11h_cvFGyNOD8")
HF_TOKEN = os.environ.get("HF_TOKEN", "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")
GIPHY_API_KEY = os.environ.get("GIPHY_API_KEY", "qnl7ssQChTdPjsKta2Ax2LMaGXz303tq")
CUSTOM_API_URL = os.environ.get("CUSTOM_API_URL", "http://fi8.bot-hosting.net:20163/elos-gpt3")

# Render automatically sets this
URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", 8000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== API FUNCTIONS ====================

def call_custom_api(question):
    try:
        url = f"{CUSTOM_API_URL}?text={requests.utils.quote(question)}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("response", "")
    except Exception as e:
        logger.error(f"Custom API error: {e}")
    return ""

def call_gemini(question):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": f"Respond in Hinglish: {question}"}]}]
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()
        if "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Gemini error: {e}")
    return ""

def call_huggingface(question):
    url = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    try:
        resp = requests.post(url, headers=headers, json={"inputs": question}, timeout=15)
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            return data[0].get("generated_text", "")
    except Exception as e:
        logger.error(f"HF error: {e}")
    return ""

def fetch_gif(query):
    url = f"https://api.giphy.com/v1/gifs/search?api_key={GIPHY_API_KEY}&q={requests.utils.quote(query)}&limit=1"
    try:
        resp = requests.get(url)
        data = resp.json()
        if data.get("data") and len(data["data"]) > 0:
            return data["data"][0]["images"]["fixed_height"]["url"]
    except Exception as e:
        logger.error(f"Giphy error: {e}")
    return ""

def local_command(text):
    lower = text.lower()
    if "time" in lower:
        return f"Abhi time hai {datetime.now().strftime('%I:%M %p')}."
    if "date" in lower:
        return f"Aaj ki date {datetime.now().strftime('%d/%m/%Y')} hai."
    if "hello" in lower or "namaste" in lower or "hi" in lower:
        return "Namaste! Main DEX AI hoon. Kaise madad karun?"
    if "how are you" in lower:
        return "Main theek hoon, aap batao?"
    if "your name" in lower:
        return "Main DEX AI hoon."
    if "joke" in lower:
        jokes = [
            "Doctor: Aapko roj apple khana chahiye. Patient: Kya isse bimari door hogi? Doctor: Nahi, par doctor door rahega!",
            "Santa: Mujhe aaj ek ghoda mila. Banta: Kahan? Santa: Lottery ticket mein!"
        ]
        return random.choice(jokes)
    return None

def get_ai_response(text):
    # Local command
    local = local_command(text)
    if local:
        return local
    
    # Try custom API
    custom = call_custom_api(text)
    if custom:
        return custom
    
    # Try Gemini
    gemini = call_gemini(text)
    if gemini:
        return gemini
    
    # Try Hugging Face
    hf = call_huggingface(text)
    if hf:
        return hf
    
    return "Samajh nahi aaya. Kuch aur poochho?"

# ==================== BOT HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(f"Namaste {user.first_name}! Main DEX AI hoon. Kuch bhi poochho!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    logger.info(f"User: {user_text}")
    
    response = get_ai_response(user_text)
    
    # Check for GIF
    if "gif of" in user_text.lower():
        query = user_text.lower().replace("gif of", "").strip()
        if query:
            gif_url = fetch_gif(query)
            if gif_url:
                await update.message.reply_animation(gif_url, caption=f"Yeh lo GIF '{query}' ka.")
                return
    
    await update.message.reply_text(response)

# ==================== WEBHOOK SETUP ====================

async def main():
    # Create bot application
    app = Application.builder().token(BOT_TOKEN).updater(None).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Set webhook
    if URL:
        webhook_url = f"{URL}/telegram"
        await app.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)
        logger.info(f"Webhook set to {webhook_url}")
    
    # Starlette routes
    async def telegram(request: Request) -> Response:
        """Handle incoming Telegram updates"""
        try:
            data = await request.json()
            update = Update.de_json(data, app.bot)
            await app.update_queue.put(update)
            return Response()
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return Response(status_code=500)
    
    async def health(request: Request) -> PlainTextResponse:
        """Health check endpoint - Render needs this"""
        return PlainTextResponse("OK")
    
    starlette_app = Starlette(routes=[
        Route("/telegram", telegram, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
        Route("/", health, methods=["GET"]),
    ])
    
    # Run both bot and web server
    web = uvicorn.Server(
        uvicorn.Config(
            app=starlette_app,
            host="0.0.0.0",
            port=PORT,
            log_level="info"
        )
    )
    
    async with app:
        await app.start()
        await web.serve()
        await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
