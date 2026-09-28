"""Interactive helper: prints a Pyrogram session string for SESSION_STRING.

    pip install pyrogram tgcrypto
    python scripts/gen_session.py
"""

import asyncio
import getpass

from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded


async def run() -> None:
    api_id = int(input("API_ID: ").strip())
    api_hash = input("API_HASH: ").strip()
    phone = input("Phone (with country code, e.g. +91XXXXXXXXXX): ").strip()

    app = Client(":gen_session:", api_id=api_id, api_hash=api_hash, in_memory=True)
    await app.connect()
    sent = await app.send_code(phone)
    code = input("Login code (from Telegram app): ").strip()
    try:
        await app.sign_in(phone, sent.phone_code_hash, code)
    except SessionPasswordNeeded:
        password = getpass.getpass("Two-step verification password: ")
        await app.check_password(password)
    print("\n✅ SESSION_STRING:\n")
    print(await app.export_session_string())
    await app.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
