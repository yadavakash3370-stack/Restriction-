import os
import asyncio
from flask import Flask
from threading import Thread
from pyrogram import Client, filters, idle
from pyrogram.errors import RPCError

# === Configuration ===
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SESSION_STRING = os.environ.get("SESSION_STRING")

# === Flask dummy server ===
web = Flask('')

@web.route('/')
def home():
    return "Bot is alive!"

def run_web():
    web.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

Thread(target=run_web).start()

# === Pyrogram Clients ===
bot = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)


def parse_link(link: str):
    link = link.strip().rstrip("/")
    parts = link.split("/")
    msg_id = int(parts[-1])

    if "c" in parts:
        idx = parts.index("c")
        chat_id_raw = parts[idx + 1]
        chat_id = int(f"-100{chat_id_raw}")
        return chat_id, msg_id
    else:
        username = parts[-2]
        return username, msg_id


@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply(
        "👋 Mujhe koi bhi Telegram link bhejiye (Public ya Private),\n"
        "Main uska restricted content nikal kar de dunga!"
    )


@bot.on_message(filters.text & ~filters.command("start"))
async def link_handler(client, message):
    text = message.text.strip()

    if "t.me/" not in text:
        await message.reply("⚠️ Please send a valid Telegram message link.")
        return

    status = await message.reply("⏳ Fetching message, please wait...")

    try:
        chat_target, msg_id = parse_link(text)

        try:
            await user.join_chat(chat_target)
        except Exception:
            pass

        msg = await user.get_messages(chat_target, msg_id)

        if msg is None or msg.empty:
            await status.edit("❌ Message not found or no access.")
            return

        if not msg.media:
            if msg.text:
                await message.reply(f"📄 Message content:\n\n{msg.text}")
            else:
                await status.edit("❌ This message has no media or text.")
            return

        await status.edit("⬇️ Downloading media...")
        file_path = await user.download_media(msg)

        await status.edit("⬆️ Uploading to you...")
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

    except RPCError as e:
        await status.edit(f"❌ Telegram error: {e}")
    except Exception as e:
        await status.edit(f"❌ Error: {e}")


async def main():
    print("⚡ Starting User Client...")
    await user.start()
    print("⚡ Starting Bot Client...")
    await bot.start()
    print("✅ BOTH CLIENTS ARE LIVE!")
    await idle()
    await user.stop()
    await bot.stop()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
