from ultimate_guillotine.core.signature import BOT_SIGNATURE, is_signed, sign


def test_sign_appends_once() -> None:
    once = sign("hello")
    assert once == f"hello\n{BOT_SIGNATURE}"
    assert sign(once) == once


def test_is_signed() -> None:
    assert is_signed(sign("x"))
    assert not is_signed("x")
