"""
Hermes tool handlers and slash-command handler for the chinese-tutor plugin.

All public functions follow the Hermes handler contract:
    def handler(args: dict, **kwargs) -> str
        • args  – dict of tool parameters (may be empty)
        • kwargs – any extra context Hermes injects (ignored here)
        • return – JSON string; never raises

The DB is initialised on first import so every hot-reload or fresh start
automatically migrates the schema and loads vocabulary if the .apkg is present.
"""

import json

from . import db as _db

# One-time setup: idempotent, safe to call multiple times
_db.init_db()


# ──────────────────────────────────────────────────────────────────────────────
# Tool: get_next_word
# ──────────────────────────────────────────────────────────────────────────────

def get_next_word_handler(args: dict, **kwargs) -> str:
    """
    Return the next word due for review.

    Response shape:
        { word_id, character, pinyin, meaning, hsk_level }
    or
        { error: "..." }
    """
    try:
        word = _db.get_next_due_word()
        if word is None:
            return json.dumps({
                "error": (
                    "No vocabulary found. "
                    "Place hsk.apkg in ~/.hermes/plugins/chinese-tutor/data/ "
                    "and delete the 'vocab_loaded' row from the meta table to reload."
                )
            })
        return json.dumps(word)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ──────────────────────────────────────────────────────────────────────────────
# Tool: check_answer
# ──────────────────────────────────────────────────────────────────────────────

def check_answer_handler(args: dict, **kwargs) -> str:
    """
    Validate the user's answer and update SM-2 state.

    Required args:
        word_id     (int)  – the id returned by get_next_word
        user_answer (str)  – Chinese characters typed by the user

    Response shape:
        { correct, user_answer, expected_character, pinyin, meaning, new_interval_days }
    """
    try:
        raw_id = args.get("word_id")
        user_answer = str(args.get("user_answer", "")).strip()

        if raw_id is None:
            return json.dumps({"error": "word_id is required"})
        if not user_answer:
            return json.dumps({"error": "user_answer must not be empty"})

        try:
            word_id = int(raw_id)
        except (TypeError, ValueError):
            return json.dumps({"error": f"word_id must be an integer, got: {raw_id!r}"})

        word = _db.get_word_by_id(word_id)
        if word is None:
            return json.dumps({"error": f"No word found with word_id={word_id}"})

        # Exact character match; Hermes/Qwen handles fuzzy feedback in prose
        correct = user_answer == word["character"]
        new_interval = _db.update_sm2(word_id, correct)

        return json.dumps({
            "correct":            correct,
            "user_answer":        user_answer,
            "expected_character": word["character"],
            "pinyin":             word["pinyin"],
            "meaning":            word["meaning"],
            "new_interval_days":  new_interval,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ──────────────────────────────────────────────────────────────────────────────
# Tool: get_progress
# ──────────────────────────────────────────────────────────────────────────────

def get_progress_handler(args: dict, **kwargs) -> str:
    """
    Return overall study statistics.

    Response shape:
        {
          total_vocabulary, words_seen, accuracy_pct,
          current_streak_days, words_due_today,
          by_hsk_level: { hsk_1: { total_words, words_seen, accuracy_pct }, … }
        }
    """
    try:
        stats = _db.get_stats()
        return json.dumps(stats)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ──────────────────────────────────────────────────────────────────────────────
# Slash command: /chinese
# ──────────────────────────────────────────────────────────────────────────────

def chinese_command_handler(args: dict, **kwargs) -> str:
    """
    Entry point for the /chinese Telegram slash command.

    Fetches the next due word and returns a structured payload that Qwen wraps
    in natural language before presenting it to the user.  Qwen is responsible
    for all conversational framing ("Here's your next word!" etc.).

    Response shape (success):
        {
          status: "ready",
          word:   { word_id, character, pinyin, meaning, hsk_level },
          prompt: "What are the pinyin and meaning of this character?"
        }

    Response shape (no vocabulary):
        { status: "no_words", message: "..." }
    """
    try:
        word = _db.get_next_due_word()
        if word is None:
            return json.dumps({
                "status": "no_words",
                "message": (
                    "No vocabulary loaded. "
                    "Add hsk.apkg to ~/.hermes/plugins/chinese-tutor/data/ and restart."
                ),
            })

        return json.dumps({
            "status": "ready",
            "word":   word,
            # Telling Qwen exactly what to ask keeps the interaction focused
            "prompt": "Ask the user to type the Chinese character shown, "
                      "then call check_answer with their response.",
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})
