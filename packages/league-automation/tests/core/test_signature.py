from ultimate_guillotine.core.signature import BOT_SIGNATURE, is_signed, sign


def test_sign_appends_once() -> None:
    once = sign("hello")
    assert once == f"hello\n{BOT_SIGNATURE}"
    assert sign(once) == once


def test_is_signed() -> None:
    assert is_signed(sign("x"))
    assert not is_signed("x")


def test_the_bot_signs_as_daddy_with_a_bottle() -> None:
    assert BOT_SIGNATURE == "— 🍼 Daddy"
    assert sign("🚨 Trade T-2026-003 logged · A ↔ B").endswith("\n— 🍼 Daddy")
    assert is_signed(sign("hello"))


def test_the_old_signature_is_still_the_bots_own() -> None:
    """Posts from before the rename sit in the chat history; a replay must not
    read them as a member's announcement."""
    assert is_signed("🚨 Trade T-2026-001 logged\n— 🤖 Guillotine Bot")
    assert not is_signed("🚨 Trade alert: A sends B to C for 10")
