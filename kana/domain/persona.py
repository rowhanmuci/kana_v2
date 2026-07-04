"""人格 prompt 組裝：把角色包（靜態）與當下處境（動態）拼成 system prompt。

結構刻意分三段，配合 LLM 的 prompt cache / KV cache：
  1. 靜態前綴：core + speech + 背景 + 品味 —— 建構時組一次快取，永不變動
  2. 動態段：當前狀態、與對方的關係、extra_sections
  3. 靜態尾段：never 清單 + 收尾指令 —— 離輸出最近的指令最有效，所以壓陣
extra_sections 是 Phase 2+ 的注入口（記憶檢索、生活事件、知識筆記），
新增動態內容只要多塞一個 PromptSection，這裡的簽名不用再改。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..infra.models import PersonaState, Relationship
from ..util import now_taipei
from .character import Character

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


@dataclass(frozen=True)
class PromptSection:
    """一段動態注入的 prompt。title 會被包成 [title] 標頭。"""

    title: str
    content: str


class PersonaPromptBuilder:
    def __init__(self, character: Character):
        self._character = character

        prefix_parts = [character.core, character.speech]
        if character.backstory:
            prefix_parts.append("[背景]\n" + character.backstory)
        if character.tastes:
            prefix_parts.append("[品味]\n" + character.tastes)
        self._static_prefix = "\n\n".join(prefix_parts)

        self._static_tail = "\n\n".join([
            character.never,
            f"根據以上，用{character.name}的方式自然回應。"
            "對話歷史裡的 [日期 時間] 只是參考用的元資料，回覆中不要輸出這個格式。",
        ])

    @property
    def character(self) -> Character:
        return self._character

    def build(
        self,
        state: PersonaState,
        rel: Relationship | None,
        extra_sections: tuple[PromptSection, ...] | list[PromptSection] = (),
    ) -> str:
        now = now_taipei()
        now_str = now.strftime("%Y-%m-%d ") + _WEEKDAYS[now.weekday()] + now.strftime(" %H:%M")

        state_section = (
            "[當前狀態]\n"
            f"現在時間：{now_str}\n"
            f"你在做的事：{state.current_activity}\n"
            f"心情：{state.current_mood}\n"
            f"體力：{state.energy_level}/100"
        )

        if rel is None:
            rel_section = "[和對方的關係]\n第一次見面的陌生人。"
        else:
            facts = "、".join(rel.known_facts) if rel.known_facts else "（還不太了解）"
            rel_section = (
                "[和對方的關係]\n"
                f"名字：{rel.display_name or rel.user_id}\n"
                f"熟悉度：{rel.familiarity}　好感度：{rel.affection}　階段：{rel.relationship_stage}\n"
                f"你記得他說過：{facts}"
            )

        dynamic = [state_section, rel_section]
        dynamic += [f"[{s.title}]\n{s.content}" for s in extra_sections]

        return "\n\n".join([self._static_prefix, *dynamic, self._static_tail])
