"""Create a fresh local configuration without handling provider credentials."""
import getpass
import os
from pathlib import Path
from .private_auth import password_hash


def main():
    path = Path(os.getenv('SECRETORY_CONFIG_FILE', '.env'))
    if path.exists():
        raise SystemExit('Configuration already exists; edit it locally or use the dashboard. Nothing changed.')
    print('Create your Khadang dashboard password (minimum 16 characters).')
    password = getpass.getpass('Password: ')
    if len(password) < 16 or password != getpass.getpass('Repeat password: '):
        raise SystemExit('Password too short or confirmation differs. Nothing written.')
    example = Path(__file__).resolve().parents[1] / '.env.example'
    text = example.read_text(encoding='utf-8').replace('SECRETORY_PASSWORD_HASH=', 'SECRETORY_PASSWORD_HASH=' + password_hash(password))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        output.write(text)
    Path('runtime').mkdir(mode=0o700, exist_ok=True)
    print('Created .env with a password hash. Run python -m secretary, then open http://127.0.0.1:8780/login.')
    print('Enter your own Telegram token, numeric owner ID and provider key in Settings.')


if __name__ == '__main__':
    main()
