from kana.config import Settings


def test_defaults_and_routing():
    s = Settings(_env_file=None)
    assert s.chat_model == "qwen3:14b"
    assert s.utility_model == "qwen3:8b"

    chat = s.route("chat")
    assert chat.provider == "ollama"
    assert chat.model == s.chat_model

    mem = s.route("memory")
    assert mem.model == s.utility_model

    # 未知類型 fallback
    assert s.route("nonexistent").provider == "ollama"
