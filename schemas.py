"""
Plain dataclasses used as typed return shapes.

These are not serialised directly — tools.py converts them to dicts/JSON —
but having them here makes the expected structure explicit and aids testing.
"""

from dataclasses import dataclass, field


@dataclass
class WordResult:
    word_id:   int
    character: str
    pinyin:    str
    meaning:   str
    hsk_level: int


@dataclass
class AnswerResult:
    correct:            bool
    user_answer:        str
    expected_character: str
    pinyin:             str
    meaning:            str
    new_interval_days:  int


@dataclass
class LevelStats:
    total_words:  int
    words_seen:   int
    accuracy_pct: float


@dataclass
class ProgressResult:
    total_vocabulary:    int
    words_seen:          int
    accuracy_pct:        float
    current_streak_days: int
    words_due_today:     int
    by_hsk_level:        dict = field(default_factory=dict)
