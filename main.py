import os
import time
import math
import asyncio
import logging
import gc
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from aiohttp import web
import motor.motor_asyncio
from pyrogram.file_id import FileId

# --- CONFIGURATION ---
# Errors varaama irukka defaults vechurukken
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MONGO_URL = os.environ.get("MONGO_URL", "")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL", 0)) 
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
RENDER_URL = os.environ.get("RENDER_URL", "") 
PORT = int(os.environ.get("PORT", 8080))

# --- DESIGN SETTINGS ---
LOGO_URL = "https://i.ibb.co/dJrBFKMF/logo.jpg" 
BACKGROUND_IMG = "https://wallpaperaccess.com/full/1567665.png"
CHANNEL_LINK = "https://t.me/cinemxtic_univerz"
ADMIN_BOT_LINK = "https://t.me/Cinemxtic_univerz_admin_bot"

# --- DATABASE ---
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = db_client["RenamerBotDB"]
collection = db["files"]

# --- BOT SETUP ---
bot = Client("RenamerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=10)
routes = web.RouteTableDef()

# --- SERVER ---
@routes.get("/")
async def home(request): return web.Response(text="⚡️ Bot is Alive!")

@routes.get("/download/{hash}")
async def download_file(request):
    try:
        hash_id = request.match_info['hash']
        data = await collection.find_one({"media_id": hash_id})
        if not data: return web.Response(text="❌ Link Expired", status=404)

        try:
            try:
                msg = await bot.get_messages(BIN_CHANNEL, data['msg_id'])
            except:
                await bot.get_chat(BIN_CHANNEL)
                msg = await bot.get_messages(BIN_CHANNEL, data['msg_id'])
            media = getattr(msg, msg.media.value)
        except:
            return web.Response(text="File Missing (Check Admin Rights)", status=404)

        file_size = getattr(media, "file_size", 0)
        final_filename = data.get("custom_name", getattr(media, "file_name", "file.mp4"))

        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{final_filename}"',
            "Content-Length": str(file_size),
            "Connection": "keep-alive"
        }

        response = web.StreamResponse(status=200, reason='OK', headers=headers)
        await response.prepare(request)

        try:
            async for chunk in bot.stream_media(message=msg, limit=0, offset=0):
                if request.transport and request.transport.is_closing(): break 
                await response.write(chunk)
                gc.collect()
        except: pass
        finally:
            await response.write_eof()
            gc.collect()
            
        return response

    except Exception as e:
        return web.Response(text=f"Error: {e}")

# --- BOT COMMANDS ---
@bot.on_message(filters.command("start") & filters.private)
async def start(c, m): 
    await m.reply_text("👋 **Renamer Bot Ready!**")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file(client, message):
    if message.from_user.id != OWNER_ID: return
    # Direct Process (No Queue for safety)
    file = getattr(message, message.media.value)
    filename = getattr(file, "file_name", "file.mp4")
    await message.reply_text(f"📂 `{filename}`\n👇 **Type New Name:**", reply_markup=ForceReply(True))

@bot.on_message(filters.reply & filters.private)
async def rename_handler(client, message):
    if message.from_user.id != OWNER_ID: return
    reply = message.reply_to_message
    if not reply or not reply.media: return

    new_name = message.text
    if "." not in new_name: new_name += ".mkv"
    
    status = await message.reply_text("⚡️ **Processing...**")
    try:
        log = await reply.copy(BIN_CHANNEL)
        import secrets
        h = secrets.token_urlsafe(8)
        await collection.insert_one({"media_id": h, "msg_id": log.id, "custom_name": new_name})
        d_link = f"{RENDER_URL}/download/{h}"
        await status.edit_text(f"✅ **Renamed!**\n📥 `{d_link}`")
    except Exception as e:
        await status.edit_text(f"❌ Error: {e}")

# --- SAFE STARTUP SEQUENCE ---
async def start_services():
    print("⏳ Initializing Server...")
    
    # 1. Start Web Server FIRST (To satisfy Render)
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print("✅ Web Server Started on Port 8080")

    # 2. Start Bot SECOND
    print("🤖 Starting Telegram Bot...")
    try:
        await bot.start()
        print("✅ Bot Started Successfully")
    except Exception as e:
        print(f"⚠️ BOT START ERROR: {e}")
        # Server will keep running so we can see logs
        await idle()
        return

    # 3. Check Channel
    try:
        print("Checking Bin Channel...")
        await bot.get_chat(BIN_CHANNEL)
        print("✅ Bin Channel Connected")
    except Exception as e:
        print(f"⚠️ CHANNEL ERROR: {e} (Make sure Bot is Admin)")

    print("🚀 System Online")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
