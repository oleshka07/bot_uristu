"""Reply drafting hygiene: no emoji in generated messages."""

from app.modules.insights import ai


def test_strip_emoji_removes_pictographs_keeps_text():
    assert ai._strip_emoji("Привіт 👋, все ок 🙂!") == "Привіт, все ок!"
    assert ai._strip_emoji("Дякую! ❤️🔥") == "Дякую!"
    assert ai._strip_emoji("Домовились 👍") == "Домовились"


def test_strip_emoji_preserves_plain_and_skip():
    assert ai._strip_emoji("[SKIP]") == "[SKIP]"
    assert ai._strip_emoji("Норм, о 15:00 зустрінемось") == "Норм, о 15:00 зустрінемось"
    assert ai._strip_emoji(None) is None


def test_strip_emoji_handles_flags_and_symbols():
    # regional-indicator flags, stars, dingbats
    assert ai._strip_emoji("Готово ✅ супер ⭐") == "Готово супер"
