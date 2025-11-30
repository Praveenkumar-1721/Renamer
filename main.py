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
db = db_client["SpeedBotDB"]
collection = db["files"]

# --- BOT SETUP ---
bot = Client("RenamerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=10)
routes = web.RouteTableDef()

# --- SERVER ENGINE (RENAMING MAGIC) ---
@routes.get("/download/{hash}")
async def download_file(request):
    try:
        hash_id = request.match_info['hash']
        data = await collection.find_one({"media_id": hash_id})
        if not data: return web.Response(text="❌ Link Expired", status=404)

        try:
            msg = await bot.get_messages(BIN_CHANNEL, data['msg_id'])
            media = getattr(msg, msg.media.value)
        except:
            return web.Response(text="File Missing", status=404)

        file_size = getattr(media, "file_size", 0)
        
        # ⚠️ TRICK: Use the NEW NAME stored in Database
        final_filename = data.get("custom_name", getattr(media, "file_name", "file.mp4"))

        # HEADERS (Force Browser to save with NEW NAME)
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
                # Garbage Collection
                gc.collect()
        except: pass
        finally:
            await response.write_eof()
            gc.collect()
            
        return response

    except Exception as e:
        return web.Response(text=f"Error: {e}")

# --- WEB SERVER HOME ---
@routes.get("/")
async def home(request): return web.Response(text="⚡️ Renamer Engine Running!")

# --- BOT COMMANDS ---
@bot.on_message(filters.command("start") & filters.private)
async def start(c, m): 
    await m.reply_text("👋 **4GB Renamer Bot!**\nSend me a file, I will give you a Rename Link.")

# 1. FILE HANDLER (Ask for Name)
@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file(client, message):
    if message.from_user.id != OWNER_ID: return
    
    file = getattr(message, message.media.value)
    original_name = getattr(file, "file_name", "file.mp4")
    
    # Store message in memory to reference in next step
    # (Note: For production, DB is better, but this is simple)
    await message.reply_text(
        f"📂 **Original Name:** `{original_name}`\n\n"
        "👇 **Type the NEW NAME below:**",
        reply_markup=ForceReply(True)
    )

# 2. RENAME LOGIC (Generate Link)
@bot.on_message(filters.reply & filters.private)
async def rename_handler(client, message):
    if message.from_user.id != OWNER_ID: return
    
    # Check if reply is to a file
    reply = message.reply_to_message
    if not reply or not reply.media: return 

    new_name = message.text
    status = await message.reply_text("⚡️ **Processing...**")

    try:
        # Copy to Bin
        log = await reply.copy(BIN_CHANNEL)
        
        # Save to DB with CUSTOM NAME
        import secrets
        h = secrets.token_urlsafe(8)
        
        await collection.insert_one({
            "media_id": h,
            "msg_id": log.id,
            "custom_name": new_name # Saving the new name
        })

        d_link = f"{RENDER_URL}/download/{h}"

        await status.edit_text(
            f"✅ **Renamed Successfully!**\n\n"
            f"📝 **New Name:** `{new_name}`\n"
            f"📥 **Download Link:**\n`{d_link}`\n\n"
            f"⚠️ *Click link to download with new name!*",
            disable_web_page_preview=True
        )

    except Exception as e:
        await status.edit_text(f"Error: {e}")

# --- START ---
async def start_services():
    await bot.start()
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
  
