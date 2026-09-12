"""Розшифровка голосових: порядок провайдерів і формат запиту до Deepgram."""

import pytest

from app.core.config import settings
from app.modules.telegram_bot import transcribe


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", None)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", None)
    monkeypatch.setattr(settings, "transcribe_provider", None)
    return settings


def test_no_keys_means_no_provider_and_no_call(keys):
    assert transcribe.available_providers() == []
    assert transcribe.active_provider() is None
    assert transcribe.transcribe_ogg(b"ogg") is None


def test_deepgram_goes_first_when_its_key_is_present(keys, monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "dg")
    monkeypatch.setattr(settings, "openai_api_key", "oa")
    assert transcribe.available_providers() == ["deepgram", "openai"]
    assert transcribe.active_provider() == "deepgram"


def test_explicit_provider_is_moved_to_the_front(keys, monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "dg")
    monkeypatch.setattr(settings, "openai_api_key", "oa")
    monkeypatch.setattr(settings, "transcribe_provider", "openai")
    assert transcribe.available_providers() == ["openai", "deepgram"]


def test_deepgram_request_shape_and_parsing(keys, monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "dg-secret")
    seen = {}

    class Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kw):
            seen.update(url=url, **kw)
            return _Resp({"results": {"channels": [{"alternatives": [{"transcript": "  привіт, це тест "}]}]}})

    monkeypatch.setattr(transcribe.httpx, "Client", Client)
    assert transcribe.transcribe_ogg(b"OGGDATA") == "привіт, це тест"
    assert seen["url"] == "https://api.deepgram.com/v1/listen"
    assert seen["headers"]["Authorization"] == "Token dg-secret"
    assert seen["headers"]["Content-Type"] == "audio/ogg"
    assert seen["content"] == b"OGGDATA"
    assert seen["params"]["detect_language"] == "true"   # пишуть трьома мовами


def test_failed_provider_falls_through_to_the_next(keys, monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "dg")
    monkeypatch.setattr(settings, "openai_api_key", "oa")
    monkeypatch.setattr(transcribe, "_deepgram", lambda audio: None)
    monkeypatch.setattr(transcribe, "_whisper", lambda audio: "з віспера")
    monkeypatch.setitem(transcribe._CALLERS, "deepgram", transcribe._deepgram)
    monkeypatch.setitem(transcribe._CALLERS, "openai", transcribe._whisper)
    assert transcribe.transcribe_ogg(b"x") == "з віспера"


def test_status_route_shows_the_voice_provider(client, keys, monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "dg")
    monkeypatch.setattr(settings, "gemini_api_key", "gm")
    st = client.get("/api/integrations/telegram/status").json()
    assert st["voice_provider"] == "deepgram"
    assert st["voice_providers"] == ["deepgram", "gemini"]
