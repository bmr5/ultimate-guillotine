#: Ben (2026-09-10): the bot is "Daddy", and the bottle is its mark -- after the
#: name, since that afternoon ("move the squirt bottle emoji to after Daddy").
BOT_NAME = "Daddy"
BOT_SIGNATURE = "— Daddy 🍼"
#: Earlier posts in the chat carry the old marks; they are still the bot's own and must
#: never be read as a member's message.
LEGACY_SIGNATURES = ("— 🍼 Daddy", "— 🤖 Guillotine Bot")


def is_signed(text: str) -> bool:
    tail = text.rstrip()
    return tail.endswith(BOT_SIGNATURE) or any(tail.endswith(old) for old in LEGACY_SIGNATURES)


def sign(text: str) -> str:
    body = text.rstrip()
    return body if is_signed(body) else f"{body}\n{BOT_SIGNATURE}"
