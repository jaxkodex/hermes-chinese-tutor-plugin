# hermes-chinese-tutor-plugin

A [Hermes Agent](https://github.com/NousResearch/hermes) plugin that teaches Chinese vocabulary using HSK flashcards and SM-2 spaced repetition.

## Installation

### 1. Clone the plugin

```bash
git clone -b main \
  https://github.com/jaxkodex/hermes-chinese-tutor-plugin.git \
  ~/.hermes/plugins/chinese-tutor
```

### 2. Add your HSK deck

Export your HSK Anki deck as an `.apkg` file and copy it into the data directory:

```bash
mkdir -p ~/.hermes/plugins/chinese-tutor/data
cp /path/to/your/hsk.apkg ~/.hermes/plugins/chinese-tutor/data/hsk.apkg
```

The plugin parses the deck on first run and populates a local SQLite database. If you skip this step the plugin loads without vocabulary — place the file and delete the `vocab_loaded` row from the `meta` table to trigger a reload.

### 3. Register the plugin

If Hermes uses an explicit plugin list in its config file (`~/.hermes/config.yaml` or `~/.hermes/config.toml`), add the plugin name:

```yaml
plugins:
  - chinese-tutor
```

If Hermes auto-discovers plugins by scanning `~/.hermes/plugins/`, no config change is needed.

### 4. Restart Hermes

```bash
hermes restart   # or however you reload your instance
```

### 5. Verify

Check the Hermes logs for `chinese-tutor` and send `/chinese` in Telegram to start a practice session.

## Tools

| Tool | Description |
|---|---|
| `get_next_word` | Returns the next HSK word due for review (SM-2 scheduled) |
| `check_answer` | Validates the user's typed characters and updates spaced repetition state |
| `get_progress` | Overall stats: accuracy, streak, words due today, per-HSK-level breakdown |

## Slash command

`/chinese` — starts or resumes a vocabulary practice session.

## Data

All data lives in `~/.hermes/plugins/chinese-tutor/data/progress.db` (SQLite). The `.apkg` source file is only read once and can be removed afterwards.
