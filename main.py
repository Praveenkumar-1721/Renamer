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

# --- MEMORY QUEUE (THE FIX) ---
# Idhu dhaan un file-a nyabagam vechukum
RENAME_QUEUE = {} 

# --- DATABASE ---
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = db_client["RenamerBotDB"]
collection = db["files"]

# --- BOT SETUP ---
bot = Client("RenamerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=10)
routes = web.RouteTableDef()

# --- SERVER ENGINE ---
@routes.get("/")
async def home(request): return web.Response(text="⚡️ Bot Running!")

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
    await m.reply_text("👋 **4GB Renamer Ready!**\nSend me a file.")

# 1. FILE HANDLER (Store in Memory)
@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file(client, message):
    if message.from_user.id != OWNER_ID: return
    
    # Save File in Queue
    RENAME_QUEUE[message.from_user.id] = message
    
    file = getattr(message, message.media.value)
    filename = getattr(file, "file_name", "file.mp4")
    
    await message.reply_text(
        f"📂 **Original:** `{filename}`\n\n"
        "👇 **Type New Name below:**",
        reply_markup=ForceReply(True)
    )

# 2. RENAME HANDLER (Fix: Removed Media Check)
@bot.on_message(filters.text & filters.private & ~filters.command("start"))
async def rename_handler(client, message):
    if message.from_user.id != OWNER_ID: return
    
    # Check if user has a file in queue
    if message.from_user.id not in RENAME_QUEUE:
        # Ignore random texts if no file is pending
        return 

    # Get the original file from Memory
    original_msg = RENAME_QUEUE[message.from_user.id]
    new_name = message.text.strip()
    
    # Auto Extension Logic
    if "." not in new_name:
        try:
            media = getattr(original_msg, original_msg.media.value)
            ext = getattr(media, "file_name", "").split(".")[-1]
            if ext: new_name += f".{ext}"
        except:
            new_name += ".mkv"

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
        await status.edit_text(f"✅ **Renamed!**\n📝 `{new_name}`\n📥 **Link:**\n`{d_link}`")
        
        # Clear Memory
        del RENAME_QUEUE[message.from_user.id]

    except Exception as e:
        await status.edit_text(f"❌ Error: {e}")

# --- START SERVICE ---
async def start_services():
    print("🤖 Starting Bot...")
    await bot.start()
    try: await bot.get_chat(BIN_CHANNEL)
    except: pass
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
            
