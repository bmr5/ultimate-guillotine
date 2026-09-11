BOT_NAME = "Guillotine Bot"
BOT_SIGNATURE = "— Guillotine Bot"
# Earlier posts remain recognizable as the bot's own messages during replay.
LEGACY_SIGNATURES = ("— Daddy 🍼", "— 🍼 Daddy", "— 🤖 Guillotine Bot")
# This fixed acknowledgment is deliberately sent verbatim, without a signature.
# Recognize it as bot output as well so its echo cannot trigger another reply.
TRADE_RECORDED = "trade recorded in database"


def is_signed(text: str) -> bool:
    tail = text.rstrip()
    return (
        tail == TRADE_RECORDED
        or tail.endswith(BOT_SIGNATURE)
        or any(tail.endswith(old) for old in LEGACY_SIGNATURES)
    )


def sign(text: str) -> str:
    body = text.rstrip()
    return body if is_signed(body) else f"{body}\n{BOT_SIGNATURE}"
