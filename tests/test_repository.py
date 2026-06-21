import asyncio

from kana.infra.repository import Repositories


async def _repos(tmp_path):
    return await Repositories.create(str(tmp_path / "test.db"))


async def test_persona_singleton(tmp_path):
    repos = await _repos(tmp_path)
    try:
        s = await repos.persona.get()
        assert s.energy_level == 100
        await repos.persona.update(current_activity="lab", energy_level=60)
        s2 = await repos.persona.get()
        assert s2.current_activity == "lab"
        assert s2.energy_level == 60
    finally:
        await repos.close()


async def test_relationship_ensure_and_update(tmp_path):
    repos = await _repos(tmp_path)
    try:
        rel = await repos.relationship.ensure("u1", "小明")
        assert rel.relationship_stage == "stranger"
        # 第二次 ensure 不應覆寫
        again = await repos.relationship.ensure("u1", "改名")
        assert again.display_name == "小明"

        await repos.relationship.update("u1", known_facts=["喜歡貓", "在寫論文"], affection=20)
        got = await repos.relationship.get("u1")
        assert got.known_facts == ["喜歡貓", "在寫論文"]
        assert got.affection == 20
    finally:
        await repos.close()


async def test_message_recent_ordering(tmp_path):
    repos = await _repos(tmp_path)
    try:
        for i in range(5):
            await repos.message.add("u1", "user", f"msg{i}")
        recent = await repos.message.recent("u1", limit=3)
        assert [m.content for m in recent] == ["msg2", "msg3", "msg4"]  # 舊→新
        assert all(m.id is not None for m in recent)
    finally:
        await repos.close()


async def test_concurrent_writes_no_lock(tmp_path):
    """50 筆並發寫入：驗證不會 database locked，且全部落地。"""
    repos = await _repos(tmp_path)
    try:
        await asyncio.gather(*[
            repos.message.add("u1", "user", f"c{i}") for i in range(50)
        ])
        all_rows = await repos.message.recent("u1", limit=100)
        assert len(all_rows) == 50
    finally:
        await repos.close()
