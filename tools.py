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
                    "Ensure hsk.apkg is in the plugin's data/ directory and restart."
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
    Returns a formatted natural language message directly to prevent raw JSON leakage.
    """
    try:
        word = _db.get_next_due_word()
        if word is None:
            return (
                "No vocabulary loaded. "
                "Ensure hsk.colpkg or hsk.apkg is in the plugin's data/ directory."
            )
        
        word_id = word.get("word_id")
        character = word.get("character", "")
        pinyin = word.get("pinyin", "")
        meaning = word.get("meaning", "")
        hsk_level = word.get("hsk_level", "")
        
        # Format as a clean, natural-language message. 
        # The [WORD_ID: X] tag is for the AI to track, but looks clean to the user.
        response = f"[WORD_ID: {word_id}]\n\n"
        response += f"### Your next word to practice:\n\n"
        response += f"# {character}\n\n"
        if pinyin:
            response += f"- **Pinyin:** {pinyin}\n"
        if meaning:
            response += f"- **Meaning:** {meaning}\n"
        if hsk_level:
            response += f"- **HSK Level:** {hsk_level}\n\n"
        response += "Can you tell me the pinyin and meaning of this character? (Just type your answer, and I'll check it for you!)"
        
        return response
    except Exception as exc:
        return f"Error: {str(exc)}"
