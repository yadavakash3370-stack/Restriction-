"""Telegram link parsing.

Handles every common t.me format:

    t.me/username/123              -> public channel post
    t.me/username/45/123           -> public group topic/thread (last id is the message)
    t.me/username/123?single       -> album share link (query strings ignored)
    t.me/c/2222333/123             -> private channel/supergroup post
    t.me/c/2222333/45/123          -> private group topic/thread
    t.me/joinchat/HASH             -> invite link
    t.me/+HASH                     -> modern invite link
    t.me/username                  -> bare profile/channel link (join only)

`find_links()` extracts every Telegram link from a message,
`parse_link()` turns one link into a simple tuple. Pure stdlib, fully unit-testable.
"""

import re
from urllib.parse import unquote, urlparse

# Matches t.me / telegram.me / telegram.dog links, with or without scheme.
LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:me|dog))/[^\s<>\"']+",
    re.IGNORECASE,
)

VALID_HOSTS = {"t.me", "telegram.me", "telegram.dog"}


class LinkError(ValueError):
    """Raised when a Telegram link cannot be parsed. The message is user-safe."""


def find_links(text: str) -> list:
    """Return every Telegram link found in a block of text, in order."""
    return [m.group(0).rstrip(".,;:!?)") for m in LINK_RE.finditer(text or "")]


def parse_link(link: str):
    """Parse a single Telegram link.

    Returns one of:
        ("message", chat_ref, msg_id)  chat_ref = int chat id for private links,
                                       username str for public links
        ("invite", url)                invite-hash link, ready for join_chat()
        ("join", username)             bare public link, join-only

    Raises LinkError with a user-friendly message on bad input.
    """
    link = (link or "").strip().strip("<>\"'").rstrip(".,;:!?")
    if not link:
        raise LinkError("Empty link.")
    if not link.lower().startswith(("http://", "https://")):
        link = "https://" + link

    parsed = urlparse(link)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in VALID_HOSTS:
        raise LinkError("Only t.me / telegram.me links are supported.")

    parts = [seg for seg in parsed.path.split("/") if seg]
    if not parts:
        raise LinkError("This link has no path.")

    head = unquote(parts[0])

    # --- invite-hash links ---------------------------------------------
    if head in ("joinchat", "addlist") and len(parts) >= 2:
        token = unquote(parts[1])
        return ("invite", f"https://t.me/joinchat/{token}")
    if head.startswith("+") and len(head) > 1:
        return ("invite", f"https://t.me/joinchat/{unquote(head[1:])}")

    # --- private links: t.me/c/<chat>/<...>/<msg> -----------------------
    if head == "c":
        nums = parts[1:]
        if len(nums) < 2 or not all(n.isdigit() for n in nums):
            raise LinkError("Private links look like t.me/c/1234567/123.")
        chat_id = int("-100" + nums[0])
        return ("message", chat_id, int(nums[-1]))

    # --- public links: t.me/<username>[/<id>[/<id>]] ---------------------
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,64}", head):
        raise LinkError("That is not a valid Telegram username or link.")

    rest = parts[1:]
    if rest:
        if not all(n.isdigit() for n in rest):
            raise LinkError("Message id in the link must be a number.")
        return ("message", head, int(rest[-1]))

    # Bare link like t.me/username — nothing to mirror, join-only.
    return ("join", head)
