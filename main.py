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

# --- DATABASE ---
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = db_client["RenamerBotDB"] # New DB Name
collection = db["files"]

# --- BOT SETUP ---
bot = Client("RenamerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=10)
routes = web.RouteTableDef()

# --- SERVER ---
@routes.get("/")
async def home(request):
    return web.Response(text="⚡️ Renamer Engine Running!")

# --- THE DOWNLOADER (RENAMING MAGIC) ---
@routes.get("/download/{hash}")
async def download_file(request):
    try:
        hash_id = request.match_info['hash']
        data = await collection.find_one({"media_id": hash_id})
        if not data: return web.Response(text="File Not Found", status=404)

        try:
            try:
                msg = await bot.get_messages(BIN_CHANNEL, data['msg_id'])
            except:
                await bot.get_chat(BIN_CHANNEL) 
                msg = await bot.get_messages(BIN_CHANNEL, data['msg_id'])
            media = getattr(msg, msg.media.value)
        except:
            return web.Response(text="File Missing", status=404)

        file_size = data['file_size']
        # ⚠️ MAGIC: Use the CUSTOM NAME from Database
        file_name = data.get("custom_name", getattr(media, "file_name", "video.mp4"))
        
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
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {offset}-{offset + length - 1}/{file_size}",
            "Content-Length": str(length),
            "Connection": "keep-alive"
        }

        response = web.StreamResponse(status=resp_status, headers=headers)
        await response.prepare(request)

        # ⚠️ CRASH PROTECTION LOGIC
        chunk_counter = 0
        try:
            async for chunk in bot.stream_media(message=msg, limit=0, offset=offset):
                if request.transport and request.transport.is_closing():
                    break 
                await response.write(chunk)
                
                # Clean RAM every 50MB
                chunk_counter += 1
                if chunk_counter % 50 == 0:
                    gc.collect()
        except: pass
        finally:
            await response.write_eof()
            gc.collect() # Final Clean
            
        return response

    except Exception as e:
        return web.Response(text=f"Error: {e}")

# --- BOT COMMANDS ---
@bot.on_message(filters.command("start") & filters.private)
async def start(c, m): 
    await m.reply_text(
        "👋 **4GB Renamer Bot Ready!**\n\n"
        "1. Send me a File.\n"
        "2. I will ask for New Name.\n"
        "3. Get High Speed Link!"
    )

# 1. FILE HANDLER (Ask for Name)
@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file(client, message):
    if message.from_user.id != OWNER_ID: return
    
    file = getattr(message, message.media.value)
    original_name = getattr(file, "file_name", "file.mp4")
    
    # Store message ID temporarily in reply_markup to reference
    await message.reply_text(
        f"📂 **Original:** `{original_name}`\n\n"
        "👇 **Type New Name below:**\n"
        "_(Example: Leo Movie Tamil.mkv)_",
        reply_markup=ForceReply(True)
    )

# 2. RENAME LOGIC (Generate Link)
@bot.on_message(filters.reply & filters.private)
async def rename_handler(client, message):
    if message.from_user.id != OWNER_ID: return
    
    # Check if reply is to a file
    reply = message.reply_to_message
    if not reply or not reply.reply_to_message or not reply.reply_to_message.media:
        return 

    # Get the original file message
    original_msg = reply.reply_to_message
    new_name = message.text
    
    # Validation: Add extension if missing
    if "." not in new_name:
        original_ext = getattr(original_msg, original_msg.media.value).file_name.split(".")[-1]
        new_name = f"{new_name}.{original_ext}"

    status = await message.reply_text("⚡️ **Processing...**")

    try:
        # Copy to Bin Channel
        log = await original_msg.copy(BIN_CHANNEL)
        media = getattr(original_msg, original_msg.media.value)
        
        import secrets
        h = secrets.token_urlsafe(8)
        
        # Save to DB with CUSTOM NAME
        await collection.insert_one({
            "media_id": h,
            "msg_id": log.id,
            "file_size": getattr(media, "file_size", 0),
            "custom_name": new_name # Saving the new name
        })

        d_link = f"{RENDER_URL}/download/{h}"

        await status.edit_text(
            f"✅ **Renamed!**\n\n"
            f"📝 **Name:** `{new_name}`\n"
            f"📥 **Link:**\n`{d_link}`\n\n"
            f"⚠️ _Click link to download with new name!_",
            disable_web_page_preview=True
        )

    except Exception as e:
        await status.edit_text(f"Error: {e}")

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
    
