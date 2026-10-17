# Contributing

Use Python 3.12+ and a virtual environment. Install `python -m pip install -e '.[dev]'`.
All included smoke checks use invented data and mocked providers; they must not read your
real `.env` or send Telegram messages. Run them from a clean checkout without runtime data:

```sh
python scripts/audit_public.py
python scripts/run_offline_checks.py
```

Check `git status` and the staged diff before committing. Never attach a real transcript,
database, export, provider token, password hash, proxy profile, or personal prompt to a
test, issue, screenshot or pull request. Reproduce a problem with synthetic data instead.

Preserve the MIT license and upstream attribution. Runtime tests belong in an isolated
temporary directory, never the source tree. Use your own credentials only in ignored local
files for opt-in integration checks. The default CI suite makes no model-provider calls.
