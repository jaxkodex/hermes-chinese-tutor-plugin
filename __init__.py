"""
chinese-tutor Hermes plugin package initialiser.

DB initialisation is triggered here so that table creation and .apkg loading
happen once at plugin load time, not on the first tool call.
"""

from . import db as _db

_db.init_db()


def register(ctx):
    from . import tools as _tools

    ctx.register_tool(
        name="get_next_word",
        toolset="chinese-tutor",
        schema={"type": "object", "properties": {}, "required": []},
        handler=_tools.get_next_word_handler,
    )
    ctx.register_tool(
        name="check_answer",
        toolset="chinese-tutor",
        schema={
            "type": "object",
            "properties": {
                "word_id": {
                    "type": "integer",
                    "description": "The word_id returned by get_next_word.",
                },
                "user_answer": {
                    "type": "string",
                    "description": "The Chinese character(s) the user typed.",
                },
            },
            "required": ["word_id", "user_answer"],
        },
        handler=_tools.check_answer_handler,
    )
    ctx.register_tool(
        name="get_progress",
        toolset="chinese-tutor",
        schema={"type": "object", "properties": {}, "required": []},
        handler=_tools.get_progress_handler,
    )
    ctx.register_command(
        name="chinese",
        handler=_tools.chinese_command_handler,
        description="Start (or resume) a Chinese vocabulary practice session.",
    )
