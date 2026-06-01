"""
chinese-tutor Hermes plugin package initialiser.

Hermes adds the plugin directory to sys.path before importing, so the
sibling modules (db, tools, schemas) are importable by plain name.

DB initialisation is triggered here so that table creation and .apkg loading
happen once at plugin load time, not on the first tool call.
"""

import db as _db

_db.init_db()
