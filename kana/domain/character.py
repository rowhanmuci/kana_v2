"""角色包載入：角色是資料，引擎是程式。

角色住在 repo 根目錄的 characters/<id>/，固定檔名約定：
  character.yaml（manifest）
  core.md / speech.md / never.md（必要：人設核心、說話方式、絕對不做清單）
  backstory.md / tastes.md（選配：背景故事、品味）
  notes/（機器可改寫區，Phase 4 知識模組的種子筆記）
人格內容永遠不出現在 .py 裡；換角色 = 換目錄 + 改 CHARACTER_ID，不改程式。
不做 plugin registry / 動態 section——第二個角色出現前，固定檔名約定就夠了。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

_REQUIRED_FILES = ("core.md", "speech.md", "never.md")
_OPTIONAL_FILES = ("backstory.md", "tastes.md")


class Character(BaseModel):
    """一個角色包載入後的完整內容。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    language: str = "zh-TW"
    timezone: str = "Asia/Taipei"
    core: str
    speech: str
    never: str
    backstory: str = ""
    tastes: str = ""


def load_character(characters_dir: str | Path, char_id: str) -> Character:
    """載入 characters/<char_id>/。必要檔缺失 fail fast，選配檔缺省為空字串。"""
    root = Path(characters_dir) / char_id

    manifest_path = root / "character.yaml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"找不到角色包 manifest：{manifest_path}")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if manifest.get("id") != char_id:
        raise ValueError(f"manifest 的 id（{manifest.get('id')!r}）與目錄名（{char_id!r}）不符")

    sections: dict[str, str] = {}
    for fname in _REQUIRED_FILES:
        path = root / fname
        if not path.is_file():
            raise FileNotFoundError(f"角色包缺必要檔：{path}")
        sections[fname.removesuffix(".md")] = path.read_text(encoding="utf-8").strip()
    for fname in _OPTIONAL_FILES:
        path = root / fname
        sections[fname.removesuffix(".md")] = (
            path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        )

    return Character(**{**manifest, **sections})
