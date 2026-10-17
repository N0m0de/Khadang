# Configuration

The initializer creates a local `.env`; never commit it. Settings saved in the dashboard
update that file. Process environment variables override `.env`, so do not duplicate
mutable model/provider settings in systemd or your shell. Restart after credential/model changes.
The `SECRETORY_*` internal names are retained for compatibility; the public project is Khadang.

| Setting | Meaning |
| --- | --- |
| `OWNER_USER_ID` | Your numeric Telegram user ID, not your username |
| `OWNER_FIRST_NAME` | Your preferred display name |
| `ASSISTANT_SIGNATURE` | Optional footer; blank derives one from your name |
| `TG_BOT_TOKEN` | Your own BotFather token |
| `AI_PROVIDER` | `openai`, `anthropic`, `openrouter`, or `auto` |
| `OPENAI_API_KEY` | Your own OpenAI API key |
| `OPENAI_MODEL` | Reply and daily report model; default `gpt-4.1-mini` |
| `OPENAI_EXTRACTOR_MODEL` | Memory/export analysis model; independently configurable |
| `OPENAI_TRANSCRIPTION_MODEL` | Voice transcription model; default `whisper-1` |
| `TELEGRAM_PROXY_URL` | Optional HTTP proxy URL for Telegram only; no proxy credentials are bundled |
| `DB_PATH` | Private SQLite location, default `./runtime/khadang.db` |
| `MESSAGE_RETENTION_DAYS` | Raw-message retention, default 7 |
| `PROMPTS_DIR` | Private prompt folder, default `./prompts` |
| `DASHBOARD_PORT` | Local dashboard port, default 8780 |
| `DASHBOARD_LANG` | `en` or `fa` |
| `REPORTS_ENABLED` | Opt-in OpenAI reports at noon and midnight, Tehran time |
| `URGENT_ALERTS_ENABLED` | Opt-in local phrase-based immediate alerts |

The dashboard supports provider-specific fields. Reports and export analysis currently
use direct OpenAI; other providers receive a basic excerpt report instead. Running
multiple processes for one bot token causes Telegram polling conflicts. Use a separate
token, configuration directory and database for each owner.

## Reports and follow-ups

Noon covers midnight-to-noon; midnight covers the full preceding calendar day. Reports
are delivered to your own bot chat. A nonempty report makes one bounded OpenAI summary
and request-extraction call, with a maximum 36,000 input excerpt characters and 1,800
output tokens. Busy-day coverage limits are disclosed. API failure falls back to excerpts.

At midnight, actionable requests receive private inline cards. Done, Confirmed/attending,
or Declined resolves an item. Still pending or no answer carries it into future reports.
Noon reports also list unresolved requests. Buttons record your checklist only: they do
not send the contact a reply, accept a calendar invitation, or perform a task externally.
Multiple requests in one source message are reviewed together.

Old tasks survive raw-message deletion and service restarts. Resolve an irrelevant
suggestion with Declined. The model/rule matcher can misclassify requests. A crash between
Telegram delivery and saving its local receipt can cause a duplicate notification.

## Personalization

Use the dashboard for your own about-me, per-contact notes, relationship tags, tone,
approved memories and style learning. These are stored in the private database or
ignored prompt files. No personal prompt files are distributed in this repository.
Typing / sending a message yourself pauses automated replies in that conversation for
the configured cooldown. `/say <chat_id> <text>` sends immediately and adds attribution.

If you lose the dashboard password, stop the service and generate a new scrypt hash
locally with `secretary.private_auth.password_hash` using a hidden prompt; replace only
`SECRETORY_PASSWORD_HASH` in your private `.env` and restart. Never paste a password or
its hash into an issue.
