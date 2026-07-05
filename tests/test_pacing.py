import random

from kana.domain.pacing import ReplyPlan, buffer_window, delay_params, plan_reply, split_reply
from kana.infra.models import PersonaState, Relationship


def _state(**kw) -> PersonaState:
    return PersonaState(character_id="t", **kw)


def _rel(**kw) -> Relationship:
    return Relationship(character_id="t", user_id="cli:u1", **kw)


# ── delay_params：不回的情況 ──

def test_no_reply_when_sleeping():
    assert delay_params(_state(current_activity="sleeping"), None, "hi") is None


def test_no_reply_when_exhausted():
    assert delay_params(_state(energy_level=10), None, "hi") is None


def test_no_reply_when_irritated_and_unfamiliar():
    state = _state(current_mood="irritated")
    assert delay_params(state, _rel(familiarity=10), "hi") is None
    # 熟了就還是會回
    assert delay_params(state, _rel(familiarity=200), "hi") is not None


# ── delay_params：修正方向 ──

def test_affection_speeds_up_median():
    state = _state()
    mu_cold, _ = delay_params(state, _rel(affection=0), "hi")
    mu_warm, _ = delay_params(state, _rel(affection=500), "hi")
    assert mu_warm < mu_cold


def test_mentioning_known_fact_speeds_up():
    state = _state()
    rel = _rel(known_facts=["他養了一隻叫麻糬的貓"])
    mu_plain, _ = delay_params(state, rel, "今天天氣不錯")
    mu_fact, _ = delay_params(state, rel, "我跟你說 他養了一隻叫麻糬的貓真的很吵")
    assert mu_fact < mu_plain


# ── split_reply ──

def test_split_on_blank_lines():
    assert split_reply("第一段\n\n第二段") == ["第一段", "第二段"]


def test_split_caps_parts_and_merges_tail():
    text = "\n\n".join(f"第{i}段" for i in range(1, 6))
    parts = split_reply(text, max_parts=3)
    assert len(parts) == 3
    assert parts[2] == "第3段\n\n第4段\n\n第5段"


def test_split_single_paragraph_untouched():
    assert split_reply("只有一段 中間有\n單換行") == ["只有一段 中間有\n單換行"]


# ── plan_reply ──

def test_plan_reply_structure():
    rng = random.Random(7)
    plan = plan_reply("好啊\n\n那就明天", _state(), _rel(), "要不要出來", rng=rng)
    assert plan.parts == ["好啊", "那就明天"]
    assert len(plan.gaps) == 1
    assert plan.initial_delay >= 3.0
    assert not plan.is_empty


def test_plan_reply_scale_zero_for_cli():
    plan = plan_reply("好啊\n\n那就明天", _state(), _rel(), "hi", scale=0.0)
    assert plan.initial_delay == 0.0
    assert plan.gaps == [0.0]
    assert plan.parts == ["好啊", "那就明天"]  # 拆條不受 scale 影響


def test_plan_reply_empty_when_sleeping():
    plan = plan_reply("好", _state(current_activity="sleeping"), None, "hi")
    assert plan.is_empty


def test_empty_plan_default():
    assert ReplyPlan().is_empty


def test_buffer_window_range():
    rng = random.Random(1)
    for _ in range(50):
        assert 4.0 <= buffer_window(rng) <= 9.0
