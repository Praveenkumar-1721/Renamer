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
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MONGO_URL = os.environ.get("MONGO_URL", "")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL", 0)) 
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
RENDER_URL = os.environ.get("RENDER_URL", "") 
PORT = int(os.environ.get("PORT", 8080))

# --- MEMORY ---
RENAME_QUEUE = {}

# --- DATABASE ---
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = db_client["RenamerBotDB"]
collection = db["files"]

# --- BOT SETUP ---
bot = Client("RenamerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=50) # Increased Workers
routes = web.RouteTableDef()

# --- SERVER ---
@routes.get("/")
async def home(request): return web.Response(text="⚡️ Renamer Turbo Active!")

# --- THE DOWNLOAD ENGINE (WITH KILL SWITCH) ---
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
            return web.Response(text="File Missing", status=404)

        file_size = getattr(media, "file_size", 0)
        final_filename = data.get("custom_name", getattr(media, "file_name", "file.mp4"))

        offset = 0
        length = file_size
        range_header = request.headers.get("Range")
        resp_status = 200
        
        if range_header:
            from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
            from_bytes = int(from_bytes)
            until_bytes = int(until_bytes) if until_bytes else file_size - 1
            offset = from_bytes
            length = until_bytes - from_bytes + 1
            resp_status = 206

        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{final_filename}"',
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {offset}-{offset + length - 1}/{file_size}",
            "Content-Length": str(length),
            "Connection": "close" # ⚠️ TRICK 1: FORCE CLOSE ON FINISH/CANCEL
        }

        response = web.StreamResponse(status=resp_status, headers=headers)
        await response.prepare(request)

        try:
            # ⚠️ TRICK 2: ACTIVE CONNECTION MONITORING
            async for chunk in bot.stream_media(message=msg, limit=0, offset=offset):
                if request.transport and request.transport.is_closing():
                    break # STOP INSTANTLY IF USER CANCELS
                await response.write(chunk)
                
        except: pass
        finally:
            await response.write_eof()
            gc.collect() # ⚠️ TRICK 3: INSTANT RAM CLEAN
            
        return response

    except Exception as e:
        return web.Response(text=f"Error: {e}")

# --- BOT COMMANDS ---
@bot.on_message(filters.command("start") & filters.private)
async def start(c, m): 
    await m.reply_text("👋 **Renamer Bot Ready!**\nSend me a file.")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file(client, message):
    if message.from_user.id != OWNER_ID: return
    RENAME_QUEUE[message.from_user.id] = message
    file = getattr(message, message.media.value)
    filename = getattr(file, "file_name", "file.mp4")
    await message.reply_text(
        f"📂 **Original:** `{filename}`\n\n👇 **Type New Name:**",
        reply_markup=ForceReply(True)
    )

@bot.on_message(filters.text & filters.private & ~filters.command("start"))
async def rename_handler(client, message):
    if message.from_user.id != OWNER_ID: return
    if message.from_user.id not in RENAME_QUEUE: return

    original_msg = RENAME_QUEUE[message.from_user.id]
    new_name = message.text.strip()
    if "." not in new_name:
        try:
            ext = getattr(original_msg, original_msg.media.value).file_name.split(".")[-1]
            new_name = f"{new_name}.{ext}"
        except: new_name = f"{new_name}.mkv"

    status = await message.reply_text("⚡️ **Processing...**")

    try:
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
        await status.edit_text(f"✅ **Renamed!**\n📥 `{d_link}`")
        del RENAME_QUEUE[message.from_user.id]

    except Exception as e:
        await status.edit_text(f"Error: {e}")

# --- START SERVICE ---
async def start_services():
    print("🤖 Starting Bot...")
    await bot.start()
    try:
        print("Checking Bin Channel...")
        await bot.get_chat(BIN_CHANNEL)
        print("✅ Connected")
    except:
        print("⚠️ Bot is not Admin in Bin Channel")

    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
    
