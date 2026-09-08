BOT_SIGNATURE = "— 🤖 Guillotine Bot"


def is_signed(text: str) -> bool:
    return text.rstrip().endswith(BOT_SIGNATURE)


def sign(text: str) -> str:
    body = text.rstrip()
    return body if is_signed(body) else f"{body}\n{BOT_SIGNATURE}"
