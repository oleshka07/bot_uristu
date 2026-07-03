"""Provider-agnostic LLM layer: selection order and fallback."""

from app.modules.insights import llm


def test_provider_order_and_enabled(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.ai_provider", "openai", raising=False)
    monkeypatch.setattr("app.core.config.settings.anthropic_api_key", "a", raising=False)
    monkeypatch.setattr("app.core.config.settings.openai_api_key", "o", raising=False)
    monkeypatch.setattr("app.core.config.settings.gemini_api_key", None, raising=False)

    assert llm.enabled() is True
    # Primary first, then remaining providers with keys.
    assert llm.providers_in_order() == ["openai", "anthropic"]
    assert llm.active_provider() == "openai"


def test_disabled_without_keys(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.anthropic_api_key", None, raising=False)
    monkeypatch.setattr("app.core.config.settings.openai_api_key", None, raising=False)
    monkeypatch.setattr("app.core.config.settings.gemini_api_key", None, raising=False)
    assert llm.enabled() is False
    assert llm.active_provider() is None
    assert llm.text("s", "u") is None
    assert llm.json("s", "u", {"type": "object"}) is None


def test_fallback_to_next_provider(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.ai_provider", "anthropic", raising=False)
    monkeypatch.setattr("app.core.config.settings.anthropic_api_key", "a", raising=False)
    monkeypatch.setattr("app.core.config.settings.openai_api_key", "o", raising=False)
    monkeypatch.setattr("app.core.config.settings.gemini_api_key", None, raising=False)

    calls = []

    def boom(*a):  # anthropic fails (e.g. out of credit)
        calls.append("anthropic")
        raise RuntimeError("credit exhausted")

    def ok(*a):  # openai answers
        calls.append("openai")
        return "готово"

    monkeypatch.setitem(llm._DISPATCH, "anthropic", boom)
    monkeypatch.setitem(llm._DISPATCH, "openai", ok)

    assert llm.text("s", "u") == "готово"
    assert calls == ["anthropic", "openai"]  # tried primary, fell back
