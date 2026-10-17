"""Opt-in preparation of the current user's own single-chat export."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import time
from dotenv import load_dotenv


def main():
    load_dotenv(os.getenv('SECRETORY_CONFIG_FILE', '.env'))
    parser = argparse.ArgumentParser(description='Prepare your own single-chat HTML/JSON export for private review.')
    parser.add_argument('export', type=Path)
    parser.add_argument('--owner-name', required=True, help='Exact sender name used by you in the export')
    parser.add_argument('--contact-name', required=True, help='Exact sender name used by the other person')
    parser.add_argument('--chat-id', type=int, required=True)
    parser.add_argument('--allow-openai-analysis', action='store_true',
                        help='Explicitly authorize sending this export text to OpenAI with your key; incurs API charges')
    parser.add_argument('--max-batches', type=int, default=20, help='Refuse larger jobs unless you deliberately raise this limit')
    args = parser.parse_args()
    from .export_parser import read_html_folder, read_json_export
    from .export_import import batches, job_path, write_json, run
    messages = read_html_folder(args.export) if args.export.is_dir() else read_json_export(args.export)
    roles = {args.owner_name: 'owner', args.contact_name: 'contact'}
    if args.owner_name == args.contact_name:
        raise SystemExit('Owner and contact sender names must differ.')
    rows = [{'id': str(m['id']), 'date': m['date'], 'role': roles[m['sender']], 'text': m['text']}
            for m in messages if m['sender'] in roles]
    if not rows or not any(r['role'] == 'owner' for r in rows) or not any(r['role'] == 'contact' for r in rows):
        raise SystemExit('Both sender names must match nonempty messages in this export.')
    count = len(batches(rows))
    print(f'Export contains {len(rows)} selected text messages; analysis requires {count} fact batches plus style analysis.')
    if not args.allow_openai_analysis:
        raise SystemExit('Inspection only: no text sent or copied. Re-run with --allow-openai-analysis only after reviewing privacy and costs.')
    if count > args.max_batches:
        raise SystemExit('Batch budget exceeded. Deliberately raise --max-batches after reviewing expected API usage.')
    job = secrets.token_hex(16)
    folder = job_path(job)
    folder.mkdir(parents=True, mode=0o700)
    write_json(folder / 'status.json', {'chat_id': args.chat_id, 'created_at': int(time.time()),
                                       'status': 'pending', 'batches_total': count, 'batches_done': 0})
    fd = os.open(folder / 'source.jsonl', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + '\n')
    asyncio.run(run(job))
    print(f'Analysis ready. Review /contacts/{args.chat_id}/imports/{job} in your private dashboard.')
    print('Nothing is applied until you select memories/style and explicitly Apply.')


if __name__ == '__main__':
    main()
