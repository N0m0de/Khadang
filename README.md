# Khadang

A self-hosted Telegram assistant with per-contact writing style and memory, a private
dashboard, approval drafts, daily reports, and persistent follow-up buttons. Persian and
English are supported. Replies are clearly signed as your assistant.

Adapted from [tg-secretary](https://github.com/sepehr071/tg-secretary), under the MIT license.
See [UPSTREAM.md](UPSTREAM.md). The Python package is still called `secretary`.

## What you get

- Direct OpenAI replies, memory extraction and voice transcription; optional free Qwen with automatic OpenAI fallback, Anthropic, and OpenRouter support.
- Per-contact personas, reviewed style learning, memory controls, and approval/edit/skip drafts.
- A reply delay and owner-activity cooldown so you can answer first.
- Password-protected local dashboard; remote access through your own SSH tunnel.
- Optional noon and midnight reports (Asia/Tehran), immediate rule-based scheduling/urgency alerts,
  and inline Done / Confirmed / Declined / Still pending decisions. Open items carry forward.
- Optional analysis of **your own** Telegram HTML/JSON exports, with review before applying learning.

No API key, account, learned profile, conversation export or working deployment is included.
Every person must run their own instance with their own credentials and private storage.

## Quick start

Prerequisites: Python 3.12+, Git, your own model-provider API key with API credit, a
Telegram bot token, and a Telegram account/client that supports connecting that bot to
your personal chats with read/reply rights. A regular standalone bot cannot read your
personal account's conversations. See Telegram's [connected business bots documentation](https://core.telegram.org/api/bots/business).

```sh
git clone https://github.com/N0m0de/Khadang.git
cd Khadang
python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```sh
# Linux / macOS
source .venv/bin/activate
```

Then run:

```sh
python -m pip install -e .
python -m secretary.initialize
python -m secretary
```

Initialization asks for a new password and saves only its scrypt hash in a private `.env`.
Open **http://127.0.0.1:8780/login**, sign in, and enter your own bot token, numeric
Telegram owner ID, OpenAI key and model choices in Settings. Save, then restart the app.
For a foreground process, start `python -m secretary` again after using Restart.
The dashboard remains available for configuration even before credentials are supplied.

1. Create a bot in [BotFather](https://t.me/BotFather). Enable its Business/Secretary mode
   if offered by your Telegram client, then connect it in your account's chatbot settings.
   Menu names and account eligibility depend on Telegram; follow its current official UI.
2. Grant read/reply permissions only for the chats you want managed. Open the bot's own
   chat and send `/start`, then `/help`.
3. Set `OWNER_FIRST_NAME` in your local `.env`. An empty `ASSISTANT_SIGNATURE` derives
   `-<your name>'s Assistant`; set it explicitly to customize it.
4. New installations start paused with approval enabled. Tag contacts and inspect drafts
   before choosing automatic replies. `/resume` starts processing; `/approval` manages approval mode.

## Configuration and operation

- [Configuration, reports and follow-ups](docs/configuration.md)
- [Free Qwen with automatic OpenAI fallback](docs/qwen.md)
- [Linux server deployment and Windows tunnel](docs/deployment.md)
- [Optional private chat-export learning](docs/export-learning.md)
- [Security and data retention](SECURITY.md)
- [Contributing and offline tests](CONTRIBUTING.md)

Reports and immediate alerts are **off by default**. To opt in, edit your own `.env`:

```dotenv
REPORTS_ENABLED=true
URGENT_ALERTS_ENABLED=true
```

Restart after changing these settings. Reports run on the server without your laptop.
Report summaries send selected conversations to your configured model provider, using
OpenAI by default or Qwen first in fallback mode. Alerts use Persian/English phrase matching and can miss unusual wording or
produce false alarms. They do not schedule appointments or take emergency action.

## Your data and costs

Keep `.env`, `runtime/`, exports, learned memories and custom prompts out of Git.
OpenAI text requests use `store=false`, but OpenAI still processes the submitted text.
Replies, memory learning, voice transcription, reports and export learning can incur
provider charges. Large exports can require many requests. Set provider-side budgets
and review usage; Khadang does not enforce a hard dollar spending cap.

Live raw messages default to seven-day retention. Learned memories, summaries, profiles
and unresolved follow-ups persist separately. They are private runtime data, not source
files. Read [SECURITY.md](SECURITY.md) before enabling automation or export analysis.
