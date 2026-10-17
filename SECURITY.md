# Security and data boundaries

This repository contains application source and synthetic tests. It includes no owner
configuration, API keys, bot token, password/hash, Telegram export, trained profile,
contact memory, chat database, conversation transcript, proxy profile, or server credentials.
Your installation creates its own local `.env`, `runtime/` and prompt files.

Never upload these runtime files, even to an issue or pull request. `.gitignore` is a
convenience, not an encryption or access-control mechanism. `git add -f` overrides it.
Run `python scripts/audit_public.py` before committing. CI checks the tracked tree too.
If a real credential is ever committed, revoke it immediately; deleting the file or
making the repository private does not revoke a leaked key. Remove it from history too.

The dashboard defaults to loopback and a scrypt password hash. Keep a strong unique
password, current dependencies and SSH key access. Sessions expire; restarting signs
you out. Failed password attempts are limited in process memory. This does not replace
host security, HTTPS or firewall protection. The supported deployment is localhost or
an SSH tunnel; do not expose port 8780 publicly or enable hosted/proxy bypass mode.

The app sends conversation context to the model provider you configure. OpenAI text
requests use `store=false`; OpenAI still processes the submitted content. Enabling daily
reports sends selected daily excerpts twice a day. Export analysis sends private export
text to OpenAI. Review costs and obtain any consent you need before enabling these.
Local urgency detection does not require per-message AI calls and can miss phrases.

Raw live messages default to seven-day retention. Summaries, reviewed memories, writing
profiles and unresolved follow-ups persist separately; deleting raw text does not delete
them. Import proposals/checkpoints can contain private quotes until you remove them.
Backups, Telegram itself and provider policies have separate retention. Protect your disk
and backups; the local SQLite database and `.env` are not encrypted by this application.

Please do not post secrets or private conversations in public issues. Use GitHub's
private vulnerability reporting if the repository owner enables it. No security guarantee
can eliminate every risk; review the code and isolate each person's deployment.
