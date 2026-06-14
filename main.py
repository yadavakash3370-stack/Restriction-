import os
from flask import Flask
from threading import Thread
from pyrogram import Client, filters

# === Configuration ===
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SESSION_STRING = os.environ.get("SESSION_STRING")

# === Pyrogram Clients ===
bot = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)


def parse_link(link):
    link = link.strip().rstrip("/")
    parts = link.split("/")
    msg_id = int(parts[-1])
    if "c" in parts:
        idx = parts.index("c")
        chat_id = int(f"-100{parts[idx + 1]}")
        return chat_id, msg_id
    else:
        return parts[-2], msg_id


@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply("👋 Send me any Telegram link!")


@bot.on_message(filters.text & ~filters.command("start"))
async def link_handler(client, message):
    text = message.text.strip()
    if "t.me/" not in text:
        await message.reply("⚠️ Send valid Telegram link.")
        return

    status = await message.reply("⏳ Fetching...")
    try:
        chat_target, msg_id = parse_link(text)
        try:
            await user.join_chat(chat_target)
        except:
            pass

        msg = await user.get_messages(chat_target, msg_id)
        if not msg or msg.empty:
            await status.edit("❌ Not found.")
            return

        if not msg.media:
            if msg.text:
                await message.reply(msg.text)
            else:
                await status.edit("❌ No content.")
            return

        await status.edit("⬇️ Downloading...")
        file_path = await user.download_media(msg)
        await status.edit("⬆️ Uploading...")
        caption = msg.caption or ""

        if msg.photo:
            await bot.send_photo(message.chat.id, file_path, caption=caption)
        elif msg.video:
            await bot.send_video(message.chat.id, file_path, caption=caption)
        elif msg.document:
            await bot.send_document(message.chat.id, file_path, caption=caption)
        elif msg.audio:
            await bot.send_audio(message.chat.id, file_path, caption=caption)
        else:
            await bot.send_document(message.chat.id, file_path, caption=caption)

        await status.delete()
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await status.edit(f"❌ Error: {e}")


# === Flask dummy server ===
web = Flask('')

@web.route('/')
def home():
    return "Bot is alive!"

def run_web():
    web.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))


if __name__ == "__main__":
    # Flask alag thread me
    Thread(target=run_web, daemon=True).start()
    
    # Pyrogram ka built-in run method use karo
    user.start()
    bot.start()
    print("✅ BOTH CLIENTS ARE LIVE!")
    
    from pyrogram import idle
    idle()
    
    user.stop()
    bot.stop()
