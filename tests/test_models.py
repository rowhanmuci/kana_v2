from datetime import datetime, timezone

from kana.infra.models import Message, PersonaState, Relationship


def test_persona_defaults():
    s = PersonaState()
    assert s.current_activity == "idle"
    assert s.energy_level == 100
    assert s.updated_at.tzinfo is not None


def test_relationship_parses_iso_strings():
    rel = Relationship(
        user_id="u1",
        first_met="2026-05-01T10:00:00+00:00",
        last_interaction="2026-05-02T10:00:00+00:00",
        known_facts=["喜歡 ZUTOMAYO"],
    )
    assert isinstance(rel.first_met, datetime)
    assert rel.first_met == datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    assert rel.known_facts == ["喜歡 ZUTOMAYO"]
    assert rel.inside_jokes == []


def test_message_roundtrip_types():
    m = Message(user_id="u1", role="user", content="嗨", created_at="2026-05-01T12:00:00+00:00")
    assert m.id is None
    assert m.created_at.year == 2026
