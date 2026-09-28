"""Restriction Bot — Telegram link → media mirror bot.

Send a t.me link and the bot fetches that message with a user-mode client
(the bot's own session, or YOUR account after /login) and re-uploads the
media here. A small Flask keep-alive server runs alongside for hosting
platforms that expect a web port.
"""

import asyncio
import logging
import os
import re
import time
from threading import Thread

from flask import Flask

from pyrogram import Client, filters, idle
from pyrogram.errors import (
    ChannelInvalid,
    ChannelPrivate,
    FloodWait,
    MediaEmpty,
    MessageIdInvalid,
    MessageNotModified,
    PasswordHashInvalid,
    PeerIdInvalid,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberInvalid,
    SessionPasswordNeeded,
    Unauthorized,
    UserAlreadyParticipant,
)

import config
import storage
from links import LinkError, find_links, parse_link

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("restrictbot")

COMMANDS = ["start", "help", "login", "logout", "cancel", "stats"]
PHONE_RE = re.compile(r"^\+?\d{7,15}$")

START_TIME = time.time()


class LoginExpired(Exception):
    """Stored session string is no longer valid."""


# === Clients ================================================================
bot = Client(
    "bot_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
)
userbot = Client(
    "user_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.SESSION_STRING,
)

# Per-user clients created via /login, and in-progress login conversations.
user_clients = {}
login_states = {}
last_request = {}


# === Small helpers ==========================================================
def friendly_error(e: Exception) -> str:
    """Map common Pyrogram errors to short, user-safe messages."""
    if isinstance(e, (ChannelPrivate, ChannelInvalid)):
        return "🔒 This chat is private and the account fetching it is not a member."
    if isinstance(e, PeerIdInvalid):
        return "🔒 Can't access this chat — try /login with an account that is a member."
    if isinstance(e, MessageIdInvalid):
        return "❌ Message not found (deleted or wrong id)."
    if isinstance(e, MediaEmpty):
        return "❌ The media in that message is empty or expired."
    if isinstance(e, LoginExpired):
        return "🔑 Your login expired — /logout and /login again."
    if isinstance(e, Unauthorized):
        return "🔑 The fetch account is logged out — check SESSION_STRING."
    return "unexpected error, please try again."


async def with_flood_retry(fn, retries: int = 1):
    """Run an async call, retrying once after a short Telegram FloodWait."""
    for attempt in range(retries + 1):
        try:
            return await fn()
        except FloodWait as e:
            if attempt >= retries or e.value > 60:
                raise
            log.warning("FloodWait %ss — waiting, then retrying", e.value)
            await asyncio.sleep(e.value + 1)


def safe_edit(message, text: str) -> None:
    """Edit a status message, ignoring 'message not modified' noise."""
    async def _go():
        try:
            await message.edit(text)
        except (MessageNotModified, FloodWait):
            pass
        except Exception:
            log.debug("status edit failed", exc_info=True)
    asyncio.ensure_future(_go())


def make_progress(status, label: str):
    """Throttled progress callback: edits the status at most every 8 seconds."""
    state = {"last": 0.0}

    def cb(current, total):
        if not total:
            return
        now = time.monotonic()
        finished = current >= total
        if not finished and now - state["last"] < 8:
            return
        state["last"] = now
        pct = min(current * 100 // total, 100)
        filled = pct // 10
        bar = "█" * filled + "░" * (10 - filled)
        safe_edit(status, f"{label} {pct}%\n[{bar}]")

    return cb


def file_kind(msg) -> str:
    if msg.photo:
        return "photo"
    if msg.video:
        return "video"
    if msg.audio:
        return "audio"
    if msg.voice:
        return "voice"
    if msg.video_note:
        return "video note"
    if msg.animation:
        return "GIF"
    if msg.sticker:
        return "sticker"
    if msg.document and msg.document.file_name:
        return msg.document.file_name
    return "file"


async def send_media(chat_id, file_path, msg, caption, progress) -> None:
    """Re-upload downloaded media through the bot, preserving its type."""
    if msg.photo:
        await bot.send_photo(chat_id, file_path, caption=caption, progress=progress)
    elif msg.video:
        await bot.send_video(
            chat_id, file_path, caption=caption,
            supports_streaming=True, progress=progress,
        )
    elif msg.audio:
        await bot.send_audio(chat_id, file_path, caption=caption, progress=progress)
    elif msg.voice:
        await bot.send_voice(chat_id, file_path, caption=caption, progress=progress)
    elif msg.animation:
        await bot.send_animation(chat_id, file_path, caption=caption, progress=progress)
    elif msg.video_note:
        await bot.send_video_note(chat_id, file_path, progress=progress)
    elif msg.sticker:
        await bot.send_sticker(chat_id, file_path)
    else:
        await bot.send_document(chat_id, file_path, caption=caption, progress=progress)


async def get_fetch_client(user_id: int) -> Client:
    """Which user-mode client fetches for this user?

    Their own /login client if they have one, otherwise the bot's session.
    Starts the per-user client lazily on first use.
    """
    session = storage.get_session(user_id)
    if not session:
        return userbot
    client = user_clients.get(user_id)
    if client is not None:
        return client
    client = Client(
        f"user_{user_id}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=session,
        in_memory=True,
    )
    try:
        await client.start()
    except Exception as e:
        log.warning("Stored session for user %s is dead: %s", user_id, e)
        raise LoginExpired()
    user_clients[user_id] = client
    log.info("Started logged-in client for user %s", user_id)
    return client


async def fetch_message(fetcher: Client, chat_ref, msg_id: int):
    """Get one message, joining a public channel first only if needed.

    Fixes the old behaviour of blindly joining every channel in every link:
    we try to read first, and only join when the chat turns out to be
    inaccessible — and only public usernames (AUTO_JOIN=true).
    """
    try:
        return await with_flood_retry(lambda: fetcher.get_messages(chat_ref, msg_id))
    except (ChannelPrivate, ChannelInvalid, PeerIdInvalid):
        if not (config.AUTO_JOIN and isinstance(chat_ref, str)):
            raise
        log.info("Joining public channel %s to fetch message", chat_ref)
        try:
            await fetcher.join_chat(chat_ref)
        except UserAlreadyParticipant:
            pass
        return await with_flood_retry(lambda: fetcher.get_messages(chat_ref, msg_id))


# === Core link processing ===================================================
async def process_link(message, status, user_id: int, raw_link: str, index: int) -> bool:
    """Handle one link end-to-end. Returns True if something was delivered."""
    parsed = parse_link(raw_link)  # LinkError propagates to the caller
    kind = parsed[0]

    # Invite / bare links: just join, nothing to mirror.
    if kind in ("invite", "join"):
        safe_edit(status, f"🔗 [{index}] Joining…")
        fetcher = await get_fetch_client(user_id)
        try:
            await fetcher.join_chat(parsed[1])
        except UserAlreadyParticipant:
            await message.reply("🙂 Already a member of that chat.")
            return True
        await message.reply("✅ Joined.")
        return True

    _, chat_ref, msg_id = parsed
    safe_edit(status, f"⏳ [{index}] Fetching…")
    fetcher = await get_fetch_client(user_id)
    msg = await fetch_message(fetcher, chat_ref, msg_id)

    if not msg or msg.empty:
        await message.reply("❌ Message not found (deleted, or id out of range).")
        return False

    if not msg.media:
        text = msg.text or msg.caption
        if text:
            await message.reply(text)
            return True
        await message.reply("❌ That message has no media or text.")
        return False

    label = f"[{index}] {file_kind(msg)}"
    safe_edit(status, f"⬇️ {label} 0%")
    dl_progress = make_progress(status, f"⬇️ {label}")

    file_path = None
    try:
        file_path = await with_flood_retry(
            lambda: fetcher.download_media(msg, progress=dl_progress)
        )
        safe_edit(status, f"⬆️ {label} …")
        caption = msg.caption or ""
        await send_media(message.chat.id, file_path, msg, caption,
                         make_progress(status, f"⬆️ {label}"))
        return True
    finally:
        # Always clean up the temp file — even when download/upload raises.
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                log.warning("Could not remove temp file %s", file_path)


def allow_request(user_id: int):
    """Whitelist + cooldown + daily limit. Returns (ok, refusal_message)."""
    if config.AUTH_USERS and user_id not in config.AUTH_USERS:
        return False, "🚫 You are not authorised to use this bot."

    now = time.monotonic()
    elapsed = now - last_request.get(user_id, 0.0)
    if elapsed < config.COOLDOWN_SECONDS:
        wait = int(config.COOLDOWN_SECONDS - elapsed) + 1
        return False, f"⏳ Slow down — try again in {wait}s."

    if config.MAX_PER_DAY and storage.get_usage(user_id) >= config.MAX_PER_DAY:
        return False, "📊 Daily limit reached. Try again tomorrow (or /login with your own account)."

    last_request[user_id] = now
    return True, ""


# === Text handler (links + login conversations) ==============================
@bot.on_message(filters.private & filters.text & ~filters.command(COMMANDS))
async def text_handler(client, message):
    if not message.from_user:
        return
    user_id = message.from_user.id

    # Mid-login conversation takes priority over link parsing.
    if user_id in login_states:
        return await handle_login_step(message)

    tg_links = find_links(message.text or "")
    if not tg_links:
        await message.reply(
            "⚠️ That doesn't look like a Telegram link.\n"
            "Send one like `t.me/username/123` — see /help."
        )
        return

    ok, refusal = allow_request(user_id)
    if not ok:
        await message.reply(refusal)
        return

    batch = tg_links[: config.MAX_LINKS_PER_MESSAGE]
    status = await message.reply(f"🔍 Found {len(batch)} link(s), processing…")
    delivered = 0

    for i, raw_link in enumerate(batch, 1):
        try:
            if await process_link(message, status, user_id, raw_link, i):
                delivered += 1
            storage.increment_usage(user_id)
        except FloodWait as e:
            await message.reply(f"⏳ Telegram rate limit hit — try again in ~{e.value}s.")
            break
        except LinkError as e:
            await message.reply(f"❌ {e}")
        except Exception as e:
            log.exception("Link #%s (%s) failed", i, raw_link)
            await message.reply(f"❌ Couldn't process link #{i}: {friendly_error(e)}")
        await asyncio.sleep(1)  # be gentle with Telegram

    try:
        await status.edit(f"✅ Done — {delivered}/{len(batch)} link(s) processed.")
    except Exception:
        pass


# === Basic commands ==========================================================
@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply(
        "👋 Send me any Telegram post link (public or private) and I'll "
        "fetch the media here.\n"
        "Use /login to fetch with your own account, /help for everything else."
    )


@bot.on_message(filters.command("help"))
async def help_handler(client, message):
    await message.reply(
        "🤖 **Restriction Bot**\n\n"
        "Send any Telegram post link and I'll mirror the media into this chat.\n\n"
        "**Commands**\n"
        "/start — quick intro\n"
        "/login — fetch with your own Telegram account\n"
        "/logout — remove your login\n"
        "/cancel — abort an ongoing login\n"
        "/stats — bot stats (owner only)\n\n"
        "**Link formats**\n"
        "• `t.me/username/123`\n"
        "• `t.me/c/2222333/123` (private)\n"
        "• topic/thread links (…/45/123)\n"
        "• `t.me/joinchat/…`, `t.me/+…` (join only)\n"
        "• several links in one message"
    )


@bot.on_message(filters.command("stats"))
async def stats_handler(client, message):
    if not message.from_user or message.from_user.id not in config.OWNER_ID:
        return
    uptime = int(time.time() - START_TIME)
    h, rem = divmod(uptime, 3600)
    m, _s = divmod(rem, 60)
    await message.reply(
        f"📊 Users seen: {storage.total_users()}\n"
        f"🔑 Logged-in users: {storage.session_count()}\n"
        f"⏱ Uptime: {h}h {m}m"
    )


# === /login flow =============================================================
@bot.on_message(filters.private & filters.command("login"))
async def login_command(client, message):
    if not message.from_user:
        return
    user_id = message.from_user.id

    # /login <session_string> — direct login by pasting a session string.
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and not parts[1].startswith("/"):
        await login_with_session_string(message, user_id, parts[1].strip())
        return

    if storage.get_session(user_id):
        await message.reply("🙂 You're already logged in. Use /logout first.")
        return
    if user_id in login_states:
        await message.reply("Login already in progress — send your phone number, or /cancel.")
        return

    login_states[user_id] = {"step": "phone"}
    await message.reply(
        "🔑 **Login — step 1/3**\n"
        "Send your phone number with country code, e.g. `+91XXXXXXXXXX`.\n\n"
        "Prefer not to share your number here? Log out of the bot's flow and "
        "paste a session string instead: `/login <session_string>`.\n"
        "/cancel to abort."
    )


async def login_with_session_string(message, user_id: int, session: str):
    """Validate a pasted Pyrogram session string, then store it."""
    status = await message.reply("🔑 Validating session string…")
    client = Client(
        f":login:{user_id}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=session,
        in_memory=True,
    )
    me = None
    try:
        await client.connect()
        me = await client.get_me()
    except Exception as e:
        log.info("Session-string login rejected: %s", e)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    if not me:
        await status.edit("❌ Invalid or expired session string.")
        return

    storage.save_session(user_id, session)
    try:
        await message.delete()  # don't leave the session string in chat history
    except Exception:
        pass
    try:
        await status.delete()
    except Exception:
        pass
    await message.reply(
        f"✅ Logged in as **{me.first_name}**!\n"
        "Links you send will now be fetched with your account.\n"
        "/logout to remove it. ⚠️ Keep in mind: this grants the bot access to your account."
    )


async def handle_login_step(message):
    user_id = message.from_user.id
    state = login_states.get(user_id)
    if not state:
        return
    text = (message.text or "").strip()
    step = state["step"]

    if step == "phone":
        phone = text.replace(" ", "").replace("-", "")
        if not PHONE_RE.match(phone):
            await message.reply("⚠️ Send a valid number like `+91XXXXXXXXXX`, or /cancel.")
            return
        if not phone.startswith("+"):
            phone = "+" + phone

        client = Client(
            f":login:{user_id}",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            in_memory=True,
        )
        try:
            await client.connect()
            sent_code = await client.send_code(phone)
        except PhoneNumberInvalid:
            try:
                await client.disconnect()
            except Exception:
                pass
            await message.reply("❌ That phone number is not on Telegram. Try again or /cancel.")
            return
        except FloodWait as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            await message.reply(f"⏳ Too many attempts — wait ~{e.value}s and send the number again.")
            return
        except Exception as e:
            log.exception("send_code failed")
            try:
                await client.disconnect()
            except Exception:
                pass
            await message.reply(f"❌ Couldn't send the code ({friendly_error(e)}). Try again or /cancel.")
            return

        state.update(step="code", client=client, phone=phone,
                     code_hash=sent_code.phone_code_hash)
        await message.reply(
            "🔑 **Step 2/3** — Check your official Telegram app for the login "
            "code and send it here (e.g. `12345`).\n"
            "I'll delete your message for privacy."
        )

    elif step == "code":
        code = text.replace(" ", "")
        if not code.isdigit() or len(code) < 3:
            await message.reply("⚠️ Send just the numeric code, e.g. `12345`.")
            return
        try:
            await message.delete()  # privacy: remove the code from chat history
        except Exception:
            pass
        client = state["client"]
        try:
            await client.sign_in(state["phone"], state["code_hash"], code)
        except SessionPasswordNeeded:
            state["step"] = "password"
            await message.reply(
                "🔒 Your account has two-step verification.\n"
                "**Step 3/3** — send your password (I'll delete it right after)."
            )
            return
        except PhoneCodeInvalid:
            await message.reply("❌ Wrong code — send it again.")
            return
        except PhoneCodeExpired:
            login_states.pop(user_id, None)
            try:
                await client.disconnect()
            except Exception:
                pass
            await message.reply("⌛ Code expired — start over with /login.")
            return
        except Exception as e:
            log.exception("sign_in failed")
            login_states.pop(user_id, None)
            try:
                await client.disconnect()
            except Exception:
                pass
            await message.reply(f"❌ Login failed: {friendly_error(e)}")
            return
        await finish_login(message, user_id, client)

    elif step == "password":
        try:
            await message.delete()
        except Exception:
            pass
        client = state["client"]
        try:
            await client.check_password(text)
        except PasswordHashInvalid:
            await message.reply("❌ Wrong password — try again.")
            return
        except Exception as e:
            log.exception("check_password failed")
            login_states.pop(user_id, None)
            try:
                await client.disconnect()
            except Exception:
                pass
            await message.reply(f"❌ Login failed: {friendly_error(e)}")
            return
        await finish_login(message, user_id, client)


async def finish_login(message, user_id: int, client: Client):
    session = await client.export_session_string()
    try:
        await client.disconnect()
    except Exception:
        pass
    login_states.pop(user_id, None)
    storage.save_session(user_id, session)

    name = "your account"
    try:
        me = await get_fetch_client(user_id)
        fetched = await me.get_me()
        if fetched and fetched.first_name:
            name = fetched.first_name
    except Exception:
        log.warning("Could not start fresh client for user %s", user_id)

    await message.reply(
        f"✅ Logged in as **{name}**!\n"
        "Links you send will now be fetched with your account.\n"
        "/logout to remove it. ⚠️ This grants the bot access to your account — "
        "log out any time."
    )


@bot.on_message(filters.private & filters.command("cancel"))
async def cancel_handler(client, message):
    if not message.from_user:
        return
    state = login_states.pop(message.from_user.id, None)
    if state and state.get("client"):
        try:
            await state["client"].disconnect()
        except Exception:
            pass
    if state:
        await message.reply("❎ Login cancelled.")
    else:
        await message.reply("Nothing to cancel.")


@bot.on_message(filters.private & filters.command("logout"))
async def logout_handler(client, message):
    if not message.from_user:
        return
    user_id = message.from_user.id

    state = login_states.pop(user_id, None)
    if state and state.get("client"):
        try:
            await state["client"].disconnect()
        except Exception:
            pass

    client = user_clients.pop(user_id, None)
    if client:
        try:
            await client.stop()
        except Exception:
            pass

    removed = storage.delete_session(user_id)
    if removed:
        await message.reply("✅ Logged out. Links will use the bot's account again.")
    else:
        await message.reply("You weren't logged in.")


# === Keep-alive web server ===================================================
web = Flask(__name__)


@web.route("/")
def home():
    return "Bot is alive!"


def run_web() -> None:
    web.run(host="0.0.0.0", port=config.PORT)


# === Startup =================================================================
async def main_async() -> None:
    # Pyrogram 2.x start/stop are coroutines — the old code called them
    # synchronously, so the clients never actually started. Fixed here.
    await userbot.start()
    await bot.start()
    log.info("✅ BOTH CLIENTS ARE LIVE")
    await idle()

    await bot.stop()
    await userbot.stop()
    for client in list(user_clients.values()):
        try:
            await client.stop()
        except Exception:
            pass
    log.info("Shutdown complete")


if __name__ == "__main__":
    storage.init()
    Thread(target=run_web, daemon=True).start()
    asyncio.run(main_async())
