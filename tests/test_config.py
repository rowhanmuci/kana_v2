from kana.config import Settings


def test_defaults_and_routing():
    s = Settings(_env_file=None)
    assert s.chat_model == "qwen3:14b"
    assert s.utility_model == "qwen3:14b"  # 預設同 chat：12GB VRAM 避免模型交換

    chat = s.route("chat")
    assert chat.provider == "ollama"
    assert chat.model == s.chat_model

    mem = s.route("memory")
    assert mem.model == s.utility_model

    # 未知類型 fallback
    assert s.route("nonexistent").provider == "ollama"


def test_character_and_adapter_defaults():
    s = Settings(_env_file=None)
    assert s.character_id == "kana"
    assert s.characters_dir == "./characters"
    assert s.adapter == "discord"


def test_default_provider_drives_route():
    s = Settings(_env_file=None, default_provider="cloud")
    assert s.route("chat").provider == "cloud"
    assert s.route("nonexistent").provider == "cloud"
