"""Speech rules: quiet hours, banned words, de-duplication. Pure Python."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta


def parse_time(value: str) -> time:
    hour, minute = (int(p) for p in value.split(":")[:2])
    return time(hour, minute)


def in_quiet_hours(now: datetime, start: time, end: time) -> bool:
    current = now.time()
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


@dataclass
class Verdict:
    speak: bool
    reason: str
    text: str


@dataclass
class SpeechGate:
    quiet_start: time = time(22, 0)
    quiet_end: time = time(7, 0)
    banned_words: tuple[str, ...] = ()
    dedupe_minutes: int = 30
    hushed_until: datetime | None = None
    _recent: dict[str, datetime] = field(default_factory=dict)

    def hush(self, until: datetime | None) -> None:
        self.hushed_until = until

    def decide(self, text: str, now: datetime, urgent: bool = False) -> Verdict:
        text = " ".join(text.split())
        if not text:
            return Verdict(False, "empty", text)
        for word in self.banned_words:
            if word and word.lower() in text.lower():
                return Verdict(False, "banned_word", text)
        if not urgent:
            if self.hushed_until and now < self.hushed_until:
                return Verdict(False, "hushed", text)
            if in_quiet_hours(now, self.quiet_start, self.quiet_end):
                return Verdict(False, "quiet_hours", text)
        key = text.lower()
        seen = self._recent.get(key)
        if seen and now - seen < timedelta(minutes=self.dedupe_minutes):
            return Verdict(False, "duplicate", text)
        self._recent = {
            k: v
            for k, v in self._recent.items()
            if now - v < timedelta(minutes=self.dedupe_minutes)
        }
        self._recent[key] = now
        return Verdict(True, "ok", text)
