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
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL")) 
OWNER_ID = int(os.environ.get("OWNER_ID"))
RENDER_URL = os.environ.get("RENDER_URL") 
PORT = int(os.environ.get("PORT", 8080))

# --- MEMORY ---
RENAME_QUEUE = {}

# --- DATABASE ---
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = db_client["RenamerBotDB"]
collection = db["files"]

# --- BOT SETUP ---
bot = Client("RenamerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=10)
routes = web.RouteTableDef()

# --- SERVER ---
@routes.get("/")
async def home(request): return web.Response(text="⚡️ Renamer Engine Running!")

@routes.get("/download/{hash}")
async def download_file(request):
    try:
        hash_id = request.match_info['hash']
        data = await collection.find_one({"media_id": hash_id})
        if not data: return web.Response(text="❌ Link Expired", status=404)

        try:
            # TRY-CATCH FOR CHANNEL CONNECTION
            try:
                msg = await bot.get_messages(BIN_CHANNEL, data['msg_id'])
            except:
                # Force Refresh Peer
                await bot.get_chat(BIN_CHANNEL)
                msg = await bot.get_messages(BIN_CHANNEL, data['msg_id'])
            media = getattr(msg, msg.media.value)
        except:
            return web.Response(text="File Missing or Bot removed from Channel", status=404)

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
    await m.reply_text("👋 **4GB Renamer Bot Ready!**\nSend me a file.")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file(client, message):
    if message.from_user.id != OWNER_ID: return
    RENAME_QUEUE[message.from_user.id] = message
    file = getattr(message, message.media.value)
    original_name = getattr(file, "file_name", "file.mp4")
    await message.reply_text(
        f"📂 **Original:** `{original_name}`\n\n👇 **Type New Name:**",
        reply_markup=ForceReply(True)
    )

@bot.on_message(filters.text & filters.private & ~filters.command("start"))
async def rename_handler(client, message):
    if message.from_user.id != OWNER_ID: return
    if message.from_user.id not in RENAME_QUEUE:
        await message.reply_text("❌ Session Expired. Send file again.")
        return

    original_msg = RENAME_QUEUE[message.from_user.id]
    new_name = message.text
    if "." not in new_name:
        try:
            ext = getattr(original_msg, original_msg.media.value).file_name.split(".")[-1]
            new_name = f"{new_name}.{ext}"
        except: new_name = f"{new_name}.mkv"

    status = await message.reply_text("⚡️ **Processing...**")

    try:
        # Copy to Bin Channel
        log = await original_msg.copy(BIN_CHANNEL)
        media = getattr(original_msg, original_msg.media.value)
        
        import secrets
        h = secrets.token_urlsafe(8)
        
        await collection.insert_one({
            "media_id": h,
            "msg_id": log.id,
            "file_size": getattr(media, "file_size", 0),
            "custom_name": new_name 
        })

        d_link = f"{RENDER_URL}/download/{h}"
        await status.edit_text(f"✅ **Renamed!**\n📥 **Link:**\n`{d_link}`")
        del RENAME_QUEUE[message.from_user.id]

    except Exception as e:
        await status.edit_text(f"Error: {e}")

# --- START SERVICE (FORCE CONNECT FIX) ---
async def start_services():
    print("🤖 Starting Bot...")
    await bot.start()
    
    # ⚠️ FORCE WAKE UP: Send a message to Bin Channel
    try:
        print("🔄 Connecting to Bin Channel...")
        await bot.send_message(BIN_CHANNEL, "🤖 **Bot Started Successfully!**\nConnection Established.")
        print("✅ Bin Channel Connected & Cached!")
    except Exception as e:
        print(f"❌ Error: Bot cannot message Bin Channel! Make sure it is Admin.\nError: {e}")

    print("🌍 Starting Web Server...")
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    await idle()
