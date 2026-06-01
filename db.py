"""
Database layer for the chinese-tutor plugin.

Single SQLite file at ~/.hermes/plugins/chinese-tutor/data/progress.db.
On first run the .apkg at data/hsk.apkg is parsed and its notes are loaded
into the `vocabulary` table.  All subsequent access goes through the helpers
below; nothing outside this module touches the DB directly.
"""

import json
import os
import re
import sqlite3
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path

PLUGIN_DIR = Path.home() / ".hermes" / "plugins" / "chinese-tutor"
DATA_DIR = PLUGIN_DIR / "data"
DB_PATH = DATA_DIR / "progress.db"
APKG_PATH = DATA_DIR / "hsk.apkg"

# ──────────────────────────────────────────────────────────────────────────────
# Connection helpers
# ──────────────────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # Enable WAL for slightly safer concurrent access (Telegram bot + plugin)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ──────────────────────────────────────────────────────────────────────────────
# Schema bootstrap
# ──────────────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS vocabulary (
    word_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    character TEXT    NOT NULL,
    pinyin    TEXT    NOT NULL DEFAULT '',
    meaning   TEXT    NOT NULL DEFAULT '',
    hsk_level INTEGER NOT NULL DEFAULT 0,
    note_id   TEXT    UNIQUE          -- original Anki note id for deduplication
);

CREATE TABLE IF NOT EXISTS progress (
    word_id       INTEGER PRIMARY KEY REFERENCES vocabulary(word_id),
    ease_factor   REAL    NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 1,
    -- ISO date string so SQLite date functions work on it directly
    next_due      TEXT    NOT NULL DEFAULT (date('now')),
    last_seen     TEXT,               -- NULL = never reviewed
    repetitions   INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count   INTEGER NOT NULL DEFAULT 0
);

-- lightweight key/value store for plugin-level flags
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_db() -> None:
    """
    Create tables if missing and load vocabulary from the .apkg file exactly
    once (guarded by the 'vocab_loaded' key in the meta table).
    """
    conn = _connect()
    try:
        conn.executescript(_DDL)
        conn.commit()

        already_loaded = conn.execute(
            "SELECT value FROM meta WHERE key = 'vocab_loaded'"
        ).fetchone()

        if already_loaded is None:
            if APKG_PATH.exists():
                count = _load_apkg(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES('vocab_loaded', ?)",
                    (str(count),),
                )
            else:
                # Mark as attempted so we don't retry on every call; the user
                # can delete this row after dropping the .apkg in place.
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES('vocab_loaded', '0')"
                )
            conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# .apkg parser
# ──────────────────────────────────────────────────────────────────────────────

_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")
_HSK_TAG_RE = re.compile(r"hsk[_:\s-]*([1-6])", re.IGNORECASE)
# Anki stores HTML in fields; strip tags before storing
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _hsk_level_from_tags(tags: str) -> int:
    """Extract HSK level integer from a space-separated Anki tags string."""
    m = _HSK_TAG_RE.search(tags)
    return int(m.group(1)) if m else 0


def _hsk_level_from_deck_name(name: str) -> int:
    """Try to pull an HSK level out of a deck name like 'HSK Level 3'."""
    m = re.search(r"(?:hsk|level)[^\d]*([1-6])", name, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def _load_apkg(conn: sqlite3.Connection) -> int:
    """
    Unzip the .apkg, open the embedded Anki SQLite collection, iterate over
    notes, and INSERT them into the vocabulary table.

    .apkg layout
    ────────────
    ├── collection.anki2   (SQLite, classic format)
    ├── collection.anki21  (SQLite, present in Anki ≥ 2.1.28 – prefer this)
    └── media              (JSON mapping filenames → original names; ignored)

    Anki notes table fields of interest
    ─────────────────────────────────────
    id    – unique note id (stored as note_id for dedup)
    tags  – space-separated tag string
    flds  – field values separated by \\x1f (ASCII 31, the "unit separator")

    Field order varies by deck template.  We detect the character field by
    finding the first field that contains a CJK codepoint; the next two fields
    are assumed to be pinyin and meaning.  If the deck has a card-deck mapping
    we also try to infer HSK level from the deck name.
    """
    inserted = 0

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(str(APKG_PATH), "r") as zf:
            names = zf.namelist()

            # Prefer .anki21 (newer format) but fall back to .anki2
            collection_file = next(
                (n for n in names if n == "collection.anki21"),
                next((n for n in names if n == "collection.anki2"), None),
            )
            if collection_file is None:
                return 0

            zf.extract(collection_file, tmp)

            # Build a deck-id → hsk_level map from the col.decks JSON blob
            deck_level_map: dict[str, int] = {}
            try:
                anki = sqlite3.connect(os.path.join(tmp, collection_file))
                col_row = anki.execute("SELECT decks FROM col LIMIT 1").fetchone()
                if col_row:
                    decks_json = json.loads(col_row[0])
                    for deck_id, deck_info in decks_json.items():
                        deck_name = deck_info.get("name", "")
                        lvl = _hsk_level_from_deck_name(deck_name)
                        if lvl:
                            deck_level_map[str(deck_id)] = lvl
                anki.close()
            except Exception:
                pass  # deck name fallback is best-effort

            # card did → note id mapping so we can look up deck-based level
            note_deck_map: dict[str, str] = {}
            try:
                anki = sqlite3.connect(os.path.join(tmp, collection_file))
                for row in anki.execute("SELECT nid, did FROM cards"):
                    note_deck_map[str(row[0])] = str(row[1])
                anki.close()
            except Exception:
                pass

            # Main pass: iterate notes
            anki = sqlite3.connect(os.path.join(tmp, collection_file))
            anki.row_factory = sqlite3.Row
            try:
                notes = anki.execute("SELECT id, tags, flds FROM notes").fetchall()
            except Exception:
                anki.close()
                return 0

            for note in notes:
                raw_fields = note["flds"].split("\x1f")
                fields = [_strip_html(f) for f in raw_fields]

                # Locate the first field that looks like Chinese characters
                char_idx = next(
                    (i for i, f in enumerate(fields) if _CJK_RE.search(f)),
                    None,
                )
                if char_idx is None:
                    continue  # skip non-Chinese notes

                character = fields[char_idx]
                # The two fields immediately after the character are treated as
                # pinyin then meaning.  This matches virtually all published
                # HSK Anki decks (including the popular "HSK 1-6 with audio").
                remaining = [f for i, f in enumerate(fields) if i != char_idx]
                pinyin  = remaining[0] if len(remaining) > 0 else ""
                meaning = remaining[1] if len(remaining) > 1 else ""

                # Determine HSK level: tag > deck name > 0
                hsk_level = _hsk_level_from_tags(note["tags"])
                if not hsk_level:
                    did = note_deck_map.get(str(note["id"]), "")
                    hsk_level = deck_level_map.get(did, 0)

                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO vocabulary
                               (character, pinyin, meaning, hsk_level, note_id)
                           VALUES (?, ?, ?, ?, ?)""",
                        (character, pinyin, meaning, hsk_level, str(note["id"])),
                    )
                    inserted += 1
                except Exception:
                    continue

            anki.close()

    return inserted


# ──────────────────────────────────────────────────────────────────────────────
# Scheduling queries
# ──────────────────────────────────────────────────────────────────────────────

def get_next_due_word() -> dict | None:
    """
    Return the next word to study.

    Priority order:
      1. Words with a progress row whose next_due ≤ today  (overdue / due today)
      2. Words that have never been seen (no progress row yet), ordered by
         HSK level ascending so beginners start at level 1
      3. Fallback: the word with the oldest last_seen (nothing due yet, but the
         user asked to study)
    """
    conn = _connect()
    today = date.today().isoformat()
    try:
        row = conn.execute(
            """
            SELECT v.word_id, v.character, v.pinyin, v.meaning, v.hsk_level
            FROM   vocabulary v
            JOIN   progress   p ON v.word_id = p.word_id
            WHERE  p.next_due <= ?
            ORDER  BY p.next_due ASC, p.last_seen ASC
            LIMIT  1
            """,
            (today,),
        ).fetchone()

        if row is None:
            row = conn.execute(
                """
                SELECT v.word_id, v.character, v.pinyin, v.meaning, v.hsk_level
                FROM   vocabulary v
                LEFT   JOIN progress p ON v.word_id = p.word_id
                WHERE  p.word_id IS NULL
                ORDER  BY v.hsk_level ASC, v.word_id ASC
                LIMIT  1
                """
            ).fetchone()

        if row is None:
            row = conn.execute(
                """
                SELECT v.word_id, v.character, v.pinyin, v.meaning, v.hsk_level
                FROM   vocabulary v
                JOIN   progress   p ON v.word_id = p.word_id
                ORDER  BY p.last_seen ASC
                LIMIT  1
                """
            ).fetchone()

        return dict(row) if row else None
    finally:
        conn.close()


def get_word_by_id(word_id: int) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT word_id, character, pinyin, meaning, hsk_level FROM vocabulary WHERE word_id = ?",
            (word_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# SM-2 update
# ──────────────────────────────────────────────────────────────────────────────

def update_sm2(word_id: int, correct: bool) -> int:
    """
    Apply one SM-2 iteration and persist the result.  Returns new interval.

    SM-2 mapping used here
    ───────────────────────
    correct   → quality score 4  ("correct response after a hesitation")
    incorrect → quality score 1  ("incorrect response, but upon seeing correct
                                   answer it felt easy to remember")

    Standard SM-2 formulas
    ──────────────────────
    EF' = EF + (0.1 - (5-q)*(0.08 + (5-q)*0.02))

    For q=4:  EF' = EF + (0.1 - 0.08) = EF + 0.02  (slight improvement)
    For q=1:  EF' = EF + (0.1 - 1.28) = EF - 1.18  → floor at 1.3

    We use a simplified variant that matches the spec:
    • correct:   interval = round(prev_interval * EF), EF unchanged
    • incorrect: interval = 1,                         EF -= 0.2  (floor 1.3)

    First-time words (no progress row) start with interval=1, EF=2.5.
    """
    conn = _connect()
    try:
        today = date.today().isoformat()
        row = conn.execute(
            "SELECT ease_factor, interval_days, repetitions, correct_count, wrong_count "
            "FROM progress WHERE word_id = ?",
            (word_id,),
        ).fetchone()

        if row is None:
            ef, interval, reps, correct_cnt, wrong_cnt = 2.5, 1, 0, 0, 0
        else:
            ef       = row["ease_factor"]
            interval = row["interval_days"]
            reps     = row["repetitions"]
            correct_cnt = row["correct_count"]
            wrong_cnt   = row["wrong_count"]

        if correct:
            # Grow the interval; ease factor is intentionally left unchanged
            # (the simplified model from the spec)
            new_interval = max(1, round(interval * ef))
            new_ef = ef
            correct_cnt += 1
        else:
            # Reset interval and slightly reduce ease factor
            new_interval = 1
            new_ef = max(1.3, ef - 0.2)
            wrong_cnt += 1

        reps += 1
        next_due = (date.today() + timedelta(days=new_interval)).isoformat()

        conn.execute(
            """
            INSERT INTO progress
                (word_id, ease_factor, interval_days, next_due, last_seen,
                 repetitions, correct_count, wrong_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(word_id) DO UPDATE SET
                ease_factor   = excluded.ease_factor,
                interval_days = excluded.interval_days,
                next_due      = excluded.next_due,
                last_seen     = excluded.last_seen,
                repetitions   = excluded.repetitions,
                correct_count = excluded.correct_count,
                wrong_count   = excluded.wrong_count
            """,
            (word_id, new_ef, new_interval, next_due, today,
             reps, correct_cnt, wrong_cnt),
        )
        conn.commit()
        return new_interval
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Statistics
# ──────────────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    conn = _connect()
    try:
        today = date.today().isoformat()

        total_vocab = conn.execute("SELECT COUNT(*) FROM vocabulary").fetchone()[0]
        words_seen  = conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0]

        agg = conn.execute(
            "SELECT COALESCE(SUM(correct_count),0), COALESCE(SUM(wrong_count),0) FROM progress"
        ).fetchone()
        total_correct   = agg[0]
        total_incorrect = agg[1]
        total_attempts  = total_correct + total_incorrect
        accuracy = round(total_correct / total_attempts * 100, 1) if total_attempts else 0.0

        due_today = conn.execute(
            "SELECT COUNT(*) FROM progress WHERE next_due <= ?", (today,)
        ).fetchone()[0]

        streak = _streak(conn)

        level_rows = conn.execute(
            """
            SELECT
                v.hsk_level,
                COUNT(DISTINCT v.word_id)                       AS total,
                COUNT(DISTINCT p.word_id)                       AS seen,
                COALESCE(SUM(p.correct_count), 0)               AS correct,
                COALESCE(SUM(p.wrong_count),   0)               AS wrong
            FROM  vocabulary v
            LEFT  JOIN progress p ON v.word_id = p.word_id
            GROUP BY v.hsk_level
            ORDER BY v.hsk_level
            """
        ).fetchall()

        by_level: dict = {}
        for lr in level_rows:
            key = f"hsk_{lr['hsk_level']}" if lr["hsk_level"] else "unleveled"
            lc = lr["correct"] or 0
            lw = lr["wrong"]   or 0
            la = lc + lw
            by_level[key] = {
                "total_words": lr["total"],
                "words_seen":  lr["seen"],
                "accuracy_pct": round(lc / la * 100, 1) if la else 0.0,
            }

        return {
            "total_vocabulary":    total_vocab,
            "words_seen":          words_seen,
            "accuracy_pct":        accuracy,
            "current_streak_days": streak,
            "words_due_today":     due_today,
            "by_hsk_level":        by_level,
        }
    finally:
        conn.close()


def _streak(conn: sqlite3.Connection) -> int:
    """
    Count consecutive calendar days ending today on which at least one word
    was reviewed.  We walk backwards from today through the distinct last_seen
    dates stored in progress.
    """
    rows = conn.execute(
        "SELECT DISTINCT last_seen FROM progress WHERE last_seen IS NOT NULL ORDER BY last_seen DESC"
    ).fetchall()
    seen_dates = {r[0] for r in rows}

    streak = 0
    day = date.today()
    while day.isoformat() in seen_dates:
        streak += 1
        day -= timedelta(days=1)
    return streak
