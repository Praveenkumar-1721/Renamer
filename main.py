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
PORT = int(os.environ.get("PORT", 7860))

# --- MEMORY ---
RENAME_QUEUE = {}

# --- DESIGN SETTINGS ---
LOGO_URL = "https://i.ibb.co/dJrBFKMF/logo.jpg" 
BACKGROUND_IMG = "https://wallpaperaccess.com/full/1567665.png"
CHANNEL_LINK = "https://t.me/cinemxtic_univerz"
ADMIN_BOT_LINK = "https://t.me/Cinemxtic_univerz_admin_bot"

# --- DATABASE ---
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = db_client["RenamerBotDB"]
collection = db["files"]

# --- BOT SETUP (FIXED CONNECTION) ---
bot = Client(
    "RenamerBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=50
)
routes = web.RouteTableDef()

# --- SERVER ---
@routes.get("/")
async def home(request): return web.Response(text="⚡️ Hugging Face Bot Running!")

# --- HTML TEMPLATE ---
def get_download_page(display_name, file_size, download_link):
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{display_name}</title>
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700&family=Cinzel:wght@700&display=swap" rel="stylesheet">
        <style>
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0; padding: 0;
                background-color: #000000; 
                background-image: linear-gradient(rgba(0,0,0,0.7), rgba(0,0,0,0.7)), url('{BACKGROUND_IMG}');
                background-repeat: no-repeat; background-position: center center;
                background-attachment: fixed; background-size: cover;
                font-family: 'Montserrat', sans-serif; color: white;
                display: flex; justify-content: center; align-items: center;
                min-height: 100vh;
            }}
            .container {{ text-align: center; width: 90%; max-width: 420px; padding: 20px; }}
            .welcome {{ font-size: 12px; font-weight: 700; letter-spacing: 3px; color: #00ffcc; text-transform: uppercase; margin-bottom: 5px; text-shadow: 0px 2px 5px rgba(0,0,0,1); }}
            .brand {{ font-family: 'Cinzel', serif; font-size: 32px; color: #ffffff; margin: 0; text-shadow: 0px 4px 10px rgba(0, 0, 0, 1); }}
            .tagline {{ font-size: 10px; color: #cccccc; letter-spacing: 1px; margin-bottom: 40px; font-weight: 600; text-shadow: 0px 2px 4px rgba(0,0,0,1); }}
            .card {{
                background: #111111; padding: 35px 25px;
                border-radius: 25px; border: 2px solid #333;
                box-shadow: 0 0 30px rgba(0, 255, 204, 0.15);
                position: relative; overflow: hidden;
            }}
            .logo-img {{ width: 110px; height: 110px; border-radius: 50%; border: 4px solid #00ffcc; margin-bottom: 20px; object-fit: cover; background: #000; box-shadow: 0 0 20px rgba(0, 255, 204, 0.3); }}
            .file-title {{ font-size: 16px; font-weight: 700; color: #ffffff; margin: 10px 0; line-height: 1.5; word-wrap: break-word; white-space: pre-wrap; }}
            .file-size {{ font-size: 13px; color: #000; background: #00ffcc; padding: 5px 15px; border-radius: 50px; display: inline-block; margin-bottom: 25px; font-weight: bold; }}
            .btn-download {{
                display: block; width: 100%; padding: 15px;
                background: linear-gradient(135deg, #00ffcc, #0099ff);
                color: #000000; text-decoration: none; font-weight: 900; 
                text-transform: uppercase; letter-spacing: 1px;
                border-radius: 50px; font-size: 16px;
                box-shadow: 0 10px 25px rgba(0, 255, 204, 0.4);
                transition: transform 0.2s;
            }}
            .btn-download:active {{ transform: scale(0.95); }}
            .footer {{ margin-top: 25px; font-size: 12px; color: #888; border-top: 1px solid #333; padding-top: 15px; }}
            .footer a {{ color: #0099ff; text-decoration: none; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="welcome">Welcome To</div>
            <h1 class="brand">Cinematic Universe</h1>
            <div class="tagline">BEST COLLECTION OF LATEST MOVIES</div>
            <div class="card">
                <img src="{LOGO_URL}" alt="Logo" class="logo-img">
                <div class="file-title">{display_name}</div>
                <div class="file-size">📦 {file_size}</div>
                <a href="{download_link}" class="btn-download">⚡ Download Now</a>
                <div class="footer">
                    Produced by: <a href="{CHANNEL_LINK}" target="_blank">Cinematic Universe</a><br>
                    <span style="display:block; margin-top:5px; font-size: 11px;">If issues contact: <a href="{ADMIN_BOT_LINK}" target="_blank">@AdminBot</a></span>
                </div>
            </div>
            <script>
                setTimeout(function() {{ window.location.href = "{download_link}"; }}, 10); 
            </script>
        </div>
    </body>
    </html>
    """

@routes.get("/view/{hash}")
async def view_file(request):
    try:
        hash_id = request.match_info['hash']
        data = await collection.find_one({"media_id": hash_id})
        if not data: return web.Response(text="❌ File Not Found.", status=404)

        download_url = f"{RENDER_URL}/download/{hash_id}"
        size = data['file_size']
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024: break
            size /= 1024
        readable_size = f"{size:.2f} {unit}"
        display_name = data.get("caption", data.get("file_name"))

        return web.Response(text=get_download_page(display_name, readable_size, download_url), content_type='text/html')
    except:
        return web.Response(text="Error")

# --- DOWNLOAD ENGINE ---
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
        file_name = data.get("custom_name", getattr(media, "file_name", "file.mp4"))
        
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
            "Connection": "close"
        }

        response = web.StreamResponse(status=resp_status, headers=headers)
        if hasattr(response, 'force_close'):
            response.force_close()
        await response.prepare(request)

        try:
            async for chunk in bot.stream_media(message=msg, limit=0, offset=offset):
                if request.transport and request.transport.is_closing():
                    break 
                await response.write(chunk)
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
    await m.reply_text("👋 **Bot Ready!**\nSend me a file.")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file(client, message):
    if message.from_user.id != OWNER_ID: return
    RENAME_QUEUE[message.from_user.id] = message
    file = getattr(message, message.media.value)
    filename = getattr(file, "file_name", "file.mp4")
    await message.reply_text(f"📂 `{filename}`\n👇 **Type New Name:**", reply_markup=ForceReply(True))

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
            "custom_name": new_name,
            "caption": new_name 
        })

        d_link = f"{RENDER_URL}/view/{h}"
        await status.edit_text(f"✅ **Renamed!**\n📥 `{d_link}`")
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
    
