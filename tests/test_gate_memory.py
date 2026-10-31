from datetime import datetime, timedelta

from custom_components.cortex.gate import SpeechGate
from custom_components.cortex.memory import MemoryBook

NOON = datetime(2026, 11, 2, 12)
NIGHT = datetime(2026, 11, 2, 23)


def test_quiet_hours_and_urgent():
    g = SpeechGate()
    assert g.decide("hello", NIGHT).reason == "quiet_hours"
    assert g.decide("fire", NIGHT, urgent=True).speak


def test_dedupe_and_banned_and_hush():
    g = SpeechGate(banned_words=("secret",))
    assert g.decide("Door open", NOON).speak
    assert g.decide("door  open", NOON + timedelta(minutes=5)).reason == "duplicate"
    assert g.decide("door open", NOON + timedelta(minutes=31)).speak
    assert g.decide("the Secret plan", NOON).reason == "banned_word"
    g.hush(NOON + timedelta(hours=1))
    assert g.decide("anything", NOON).reason == "hushed"
    assert g.decide("alarm", NOON, urgent=True).speak


def test_memory_merge_recall_forget():
    b = MemoryBook()
    a = b.add("The rabbits live in the hutch by the shed", "place")
    again = b.add("rabbits live in the hutch by the shed", "place")
    assert a is again and len(b.items) == 1
    b.add("Alex likes the kitchen light at 60% in the evening", "preference")
    assert b.recall("where are the rabbit")[0].id == a.id
    assert b.forget("kitchen light").category == "preference"
    assert len(b.items) == 1
    restored = MemoryBook.from_data(b.to_data())
    assert restored.items[0].text == a.text
