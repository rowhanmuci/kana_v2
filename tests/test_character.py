from pathlib import Path

import pytest

from kana.domain.character import Character, load_character
from kana.domain.persona import PersonaPromptBuilder, PromptSection
from kana.infra.models import PersonaState, Relationship

REPO_CHARACTERS = Path(__file__).resolve().parent.parent / "characters"


def _write_package(root: Path, char_id: str = "testchar", *,
                   with_optional: bool = True, manifest_id: str | None = None) -> Path:
    d = root / char_id
    d.mkdir(parents=True)
    (d / "character.yaml").write_text(
        f"id: {manifest_id or char_id}\nname: 測試角\n", encoding="utf-8"
    )
    (d / "core.md").write_text("核心人設內容", encoding="utf-8")
    (d / "speech.md").write_text("說話方式內容", encoding="utf-8")
    (d / "never.md").write_text("絕不清單內容", encoding="utf-8")
    if with_optional:
        (d / "backstory.md").write_text("背景內容", encoding="utf-8")
        (d / "tastes.md").write_text("品味內容", encoding="utf-8")
    return root


def test_load_full_package(tmp_path):
    c = load_character(_write_package(tmp_path), "testchar")
    assert c.id == "testchar"
    assert c.name == "測試角"
    assert c.core == "核心人設內容"
    assert c.backstory == "背景內容"
    assert c.tastes == "品味內容"


def test_missing_required_file_raises(tmp_path):
    _write_package(tmp_path)
    (tmp_path / "testchar" / "core.md").unlink()
    with pytest.raises(FileNotFoundError):
        load_character(tmp_path, "testchar")


def test_optional_files_default_empty(tmp_path):
    c = load_character(_write_package(tmp_path, with_optional=False), "testchar")
    assert c.backstory == ""
    assert c.tastes == ""


def test_manifest_id_mismatch_raises(tmp_path):
    _write_package(tmp_path, manifest_id="別的id")
    with pytest.raises(ValueError):
        load_character(tmp_path, "testchar")


def test_repo_kana_package_loads():
    """repo 內建的加奈角色包必須永遠載得起來。"""
    c = load_character(REPO_CHARACTERS, "kana")
    assert c.name == "加奈"
    assert "ZUTOMAYO" in c.tastes
    assert c.core and c.speech and c.never


def _builder() -> PersonaPromptBuilder:
    return PersonaPromptBuilder(Character(
        id="t", name="測試角", core="核心人設內容", speech="說話方式內容",
        never="絕不清單內容", backstory="背景內容", tastes="品味內容",
    ))


def test_builder_section_order():
    prompt = _builder().build(PersonaState(), None)
    # 靜態前綴 → 動態段 → never 壓陣 → 收尾
    assert prompt.index("核心人設內容") < prompt.index("[當前狀態]")
    assert prompt.index("[當前狀態]") < prompt.index("[和對方的關係]")
    assert prompt.index("[和對方的關係]") < prompt.index("絕不清單內容")
    assert "用測試角的方式自然回應" in prompt
    assert "第一次見面的陌生人" in prompt


def test_builder_extra_sections_injection():
    extra = [
        PromptSection("相關記憶", "上次聊到演唱會"),
        PromptSection("今天發生的事", "baseline 又被擠掉"),
    ]
    prompt = _builder().build(PersonaState(), None, extra_sections=extra)
    assert "[相關記憶]\n上次聊到演唱會" in prompt
    assert "[今天發生的事]\nbaseline 又被擠掉" in prompt
    # extra 在關係段之後、never 之前
    assert prompt.index("[和對方的關係]") < prompt.index("[相關記憶]")
    assert prompt.index("[今天發生的事]") < prompt.index("絕不清單內容")


def test_builder_relationship_section():
    rel = Relationship(user_id="cli:u1", display_name="小明", known_facts=["剛植牙"])
    prompt = _builder().build(PersonaState(), rel)
    assert "名字：小明" in prompt
    assert "剛植牙" in prompt
