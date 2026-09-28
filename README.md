# Restriction Bot 🤖

A Telegram bot that mirrors posts from (restricted) Telegram channels and groups
into your chat. Send it a `t.me` link — it fetches the message with a user-mode
account and re-uploads the media right there.

Built with [Pyrogram](https://docs.pyrogram.org/) + Flask keep-alive server.

## ✨ Features

- 🔗 Supports **all link formats** — public posts, private `t.me/c/…` posts,
  topic/thread links, album share links, invite links, several links in one message
- 🔑 **`/login`** — users can fetch with **their own Telegram account** (phone +
  OTP code + 2FA flow, or paste a session string), so they can access chats only
  *they* are a member of
- 📊 Live **download/upload progress bar**
- 🛡 **Rate limiting** — per-user cooldown + optional daily limit
- 🚫 Optional **user whitelist** (`AUTH_USERS`)
- 🧹 Temp files always cleaned up, friendly error messages (no raw tracebacks),
  `FloodWait` aware, login codes/passwords auto-deleted from chat history
- ❤️ Keep-alive web server for Railway / Koyeb / Render / Heroku

## 📋 Commands

| Command | What it does |
|---|---|
| `/start` | Quick intro |
| `/help` | Full help |
| *(send a link)* | Fetch & mirror the media |
| `/login` | Log in with your own account (phone → code → 2FA) |
| `/login <session_string>` | Log in by pasting a Pyrogram session string |
| `/logout` | Remove your login |
| `/cancel` | Abort an ongoing login |
| `/stats` | Bot stats (owner only) |

## ⚙️ Configuration

### Required environment variables

| Variable | Where to get it |
|---|---|
| `API_ID` | [my.telegram.org](https://my.telegram.org) → API development tools |
| `API_HASH` | same as above |
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
| `SESSION_STRING` | Pyrogram **user** session string — run `python scripts/gen_session.py` locally |

> ⚠️ `SESSION_STRING` is a **full user account login**. Use a spare account,
> never share it, and never commit it anywhere.

### Optional environment variables

| Variable | Default | Meaning |
|---|---|---|
| `AUTH_USERS` | *(empty = public)* | Comma-separated user ids allowed to use the bot |
| `OWNER_ID` | *(empty)* | User ids that may use `/stats` |
| `AUTO_JOIN` | `true` | Join public channels only when needed to fetch (never auto-joins private chats) |
| `MAX_PER_DAY` | `25` | Links per user per day, `0` = unlimited |
| `COOLDOWN_SECONDS` | `5` | Minimum gap between two requests per user |
| `MAX_LINKS_PER_MESSAGE` | `10` | Cap for multi-link messages |
| `PORT` | `8080` | Keep-alive web server port |
| `DB_PATH` | `data/bot.db` | SQLite file (login sessions + usage) |

## 🚀 Deploy

### Run locally

```bash
pip install -r requirements.txt
export API_ID=123456
export API_HASH=xxxxxxxx
export BOT_TOKEN=123:abc
export SESSION_STRING=...   # from scripts/gen_session.py
python main.py
```

Run the tests:

```bash
python -m unittest discover -s tests
```

### Railway / Koyeb / Render

1. Fork this repo, create a new service from it.
2. Add the environment variables above (port is picked up automatically).
3. Deploy — the Flask server answers on `/` for health checks.

### Heroku

`runtime.txt` and `Procfile` are included — add a **worker** dyno and set the
config vars.

## 🔐 About `/login`

`/login` lets any user link their own Telegram account. Afterwards the bot
fetches links for them with **their** session — handy when a channel is private
and only that user is a member.

Things to know:

- The login code (and 2FA password, if asked) are **deleted immediately** from
  the chat history.
- Session strings are stored **plaintext** in `data/bot.db` — protect that file,
  or mount it on a private volume.
- Logging in grants the bot full access to the account. `/logout` removes the
  stored session and stops using it. Users should also terminate the session in
  Telegram Settings → Devices if they want to be thorough.
- Lock the bot down with `AUTH_USERS` if you only want trusted people to log in.

## ⚠️ Disclaimer

This project is for **educational purposes**. Don't use it to infringe
copyright, violate anyone's privacy, or break Telegram's Terms of Service.
You are responsible for what you do with it.
