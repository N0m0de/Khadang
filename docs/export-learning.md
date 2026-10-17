# Optional export learning

No export or learned profile is included in Khadang. Each user supplies their own single
chat export locally. Do not put exports inside the repository. Keep them in a private
folder outside Git, and obtain the permission appropriate to the conversation.

Export one chat with Telegram Desktop, choosing HTML or JSON. Media is not needed.
For HTML, point to the directory containing `messages.html` and the numbered pages;
for JSON, point to that chat's JSON file. Forwarded/service/media-only entries are skipped.
Use `/find <name>` in your bot or the dashboard to identify the connected chat ID.

Inspect without transmitting anything (substitute your own path, names and chat ID):

```sh
python -m secretary.import_chat /private/my-chat-export --owner-name "Alex" --contact-name "Taylor" --chat-id 123
```

It prints counts only. Exact sender names must match the export. No chat text is printed.
The first command exits after inspection. The source export is not modified.

After reviewing privacy and API costs, explicitly authorize analysis:

```sh
python -m secretary.import_chat /private/my-chat-export --owner-name "Alex" --contact-name "Taylor" --chat-id 123 --allow-openai-analysis
```

This sends the selected text to OpenAI using your key and `OPENAI_EXTRACTOR_MODEL` with
`store=false`; private/intimate text in those messages is processed by OpenAI. Each batch
may produce up to 4,000 output tokens. A large history can need many batches, retries
and a separate writing-style call. The default preparation limit is 20 batches; change
`--max-batches` deliberately if you accept a larger job. This is a request-count guard,
not an exact price estimate or a dollar spending cap.

Processing writes private checkpoints/proposals beneath your database's `imports/`
directory. Review the displayed private dashboard path, then select the style/memories
you actually want to apply. Suggestions are inactive by default. Historical facts may
be outdated. Only explicit contact quotations support fact proposals.

The normalized raw copy is deleted after successful processing. Failed jobs can leave
their private raw copy/checkpoints for recovery. The original export, proposal quotes,
reviewed profile and selected memories remain separate private files/data. To remove a
completed review from the dashboard, remove only its generated import-job directory
after applying what you want; this does not delete already applied memory/style from
SQLite. Stop any analysis of that job first. Never commit an import directory or archive.
