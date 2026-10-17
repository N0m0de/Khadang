"""Fail on tracked runtime data or common credential formats; never print matched values."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_BINARY = {'secretary/dashboard/static/fonts/Vazirmatn-Regular.woff2',
                  'secretary/dashboard/static/fonts/Vazirmatn-Bold.woff2'}
PATTERNS = {
    'provider credential': re.compile(rb'\bsk-(?:proj-|or-v1-|ant-)?[A-Za-z0-9_-]{20,}'),
    'GitHub credential': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})'),
    'Telegram credential': re.compile(rb'\b[0-9]{6,12}:[A-Za-z0-9_-]{30,}'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'password hash': re.compile(rb'scrypt\$[0-9a-f]{32}\$[0-9a-f]{64}'),
    'authenticated proxy': re.compile(rb'https?://[^\s/:"\']+:[^\s/@"\']+@'),
}
FORBIDDEN_DIRS = {'runtime', 'data', 'imports', 'exports', '__pycache__', '.venv'}
FORBIDDEN_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.session', '.pem', '.key', '.p12', '.pfx',
                      '.jsonl', '.csv', '.log', '.zip', '.tar', '.bak', '.pyc'}


def audit(files):
    problems = []
    for relative in files:
        name = relative.as_posix()
        path = ROOT / relative
        if path.is_symlink():
            problems.append((name, 'symlink'))
            continue
        if (set(relative.parts) & FORBIDDEN_DIRS or path.suffix in FORBIDDEN_SUFFIXES
                or (path.name.startswith('.env') and path.name != '.env.example')
                or path.name.startswith('messages') and path.suffix == '.html'
                or name.startswith('prompts/') or path.name == 'result.json'):
            problems.append((name, 'private/runtime path'))
        blob = path.read_bytes()
        if name in ALLOWED_BINARY:
            continue
        if b'\0' in blob:
            problems.append((name, 'unexpected binary'))
        for label, pattern in PATTERNS.items():
            if pattern.search(blob):
                problems.append((name, label))
    return problems


def main():
    result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], capture_output=True, check=True)
    files = [Path(name) for name in result.stdout.decode().split('\0') if name]
    if not files:
        raise SystemExit('No tracked/staged files found; stage the intended public source first.')
    problems = audit(files)
    for path, reason in problems:
        print(f'BLOCKED: {path}: {reason}')
    if problems:
        raise SystemExit(1)
    print(f'Public source audit passed: {len(files)} tracked files, no runtime paths or recognized credentials.')


if __name__ == '__main__':
    main()
