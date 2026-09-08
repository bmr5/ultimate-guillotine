from ultimate_guillotine.messages.fingerprint import participant_fingerprint


def test_fingerprint_is_order_and_format_insensitive() -> None:
    a = participant_fingerprint(["+1 (555) 555-0100", "ben@example.com"])
    b = participant_fingerprint(["BEN@example.com", "+15555550100"])
    assert a == b
    assert len(a) == 32


def test_fingerprint_changes_with_membership() -> None:
    assert participant_fingerprint(["+15555550100"]) != participant_fingerprint(["+15555550100", "+15555550101"])
