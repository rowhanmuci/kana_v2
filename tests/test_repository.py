import asyncio

from kana.infra.repository import Repositories


async def _repos(tmp_path):
    return await Repositories.create(str(tmp_path / "test.db"), "kana")


async def test_persona_per_character(tmp_path):
    repos = await _repos(tmp_path)
    try:
        s = await repos.persona.get()
        assert s.energy_level == 100
        assert s.character_id == "kana"
        await repos.persona.update(current_activity="lab", energy_level=60)
        s2 = await repos.persona.get()
        assert s2.current_activity == "lab"
        assert s2.energy_level == 60
    finally:
        await repos.close()


async def test_relationship_ensure_and_update(tmp_path):
    repos = await _repos(tmp_path)
    try:
        rel = await repos.relationship.ensure("cli:u1", "小明")
        assert rel.relationship_stage == "stranger"
        assert rel.character_id == "kana"
        # 第二次 ensure 不應覆寫
        again = await repos.relationship.ensure("cli:u1", "改名")
        assert again.display_name == "小明"

        await repos.relationship.update("cli:u1", known_facts=["喜歡貓", "在寫論文"], affection=20)
        got = await repos.relationship.get("cli:u1")
        assert got.known_facts == ["喜歡貓", "在寫論文"]
        assert got.affection == 20
    finally:
        await repos.close()


async def test_message_recent_ordering(tmp_path):
    repos = await _repos(tmp_path)
    try:
        for i in range(5):
            await repos.message.add("cli:u1", "user", f"msg{i}")
        recent = await repos.message.recent("cli:u1", limit=3)
        assert [m.content for m in recent] == ["msg2", "msg3", "msg4"]  # 舊→新
        assert all(m.id is not None for m in recent)
    finally:
        await repos.close()


async def test_concurrent_writes_no_lock(tmp_path):
    """50 筆並發寫入：驗證不會 database locked，且全部落地。"""
    repos = await _repos(tmp_path)
    try:
        await asyncio.gather(*[
            repos.message.add("cli:u1", "user", f"c{i}") for i in range(50)
        ])
        all_rows = await repos.message.recent("cli:u1", limit=100)
        assert len(all_rows) == 50
    finally:
        await repos.close()


async def test_character_isolation(tmp_path):
    """同一個 DB 檔、兩個角色的 Repositories：資料完全隔離。"""
    path = str(tmp_path / "multi.db")
    a = await Repositories.create(path, "alpha")
    b = await Repositories.create(path, "beta")
    try:
        # relationship 隔離
        await a.relationship.ensure("cli:u1", "A看到的")
        assert await b.relationship.get("cli:u1") is None

        # message 隔離
        await a.message.add("cli:u1", "user", "hello-a")
        assert await b.message.recent("cli:u1") == []

        # persona_state 隔離
        await a.persona.update(current_activity="lab")
        state_b = await b.persona.get()
        assert state_b.current_activity == "idle"
        assert state_b.character_id == "beta"

        # memory 隔離
        await a.memory.add("self", "a 的記憶")
        assert await b.memory.recent() == []
        assert len(await a.memory.recent()) == 1
    finally:
        await a.close()
        await b.close()
