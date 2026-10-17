"""Fresh-user setup uses invented password and opens no provider/Telegram connections."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import urllib.request
import socket

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from secretary import initialize

with tempfile.TemporaryDirectory() as temporary:
    previous = Path.cwd()
    os.chdir(temporary)
    try:
        path = Path(temporary) / '.env'
        with patch.dict(os.environ, {'SECRETORY_CONFIG_FILE': str(path)}), \
             patch.object(initialize.getpass, 'getpass', return_value='fictional-test-passphrase'):
            initialize.main()
            assert path.exists() and 'OPENAI_API_KEY=\n' in path.read_text()
            assert 'fictional-test-passphrase' not in path.read_text()
            original = path.read_bytes()
            try:
                initialize.main()
            except SystemExit:
                pass
            assert path.read_bytes() == original
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        env = dict(os.environ, PYTHONPATH=str(root), SECRETORY_CONFIG_FILE=str(path), DASHBOARD_PORT=str(port))
        for key in ('TG_BOT_TOKEN', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY', 'SECRETORY_PASSWORD_HASH', 'SECRETORY_PRIVATE_AUTH'):
            env.pop(key, None)
        process = subprocess.Popen([sys.executable, '-m', 'secretary'], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            ready = False
            for _ in range(60):
                if process.poll() is not None:
                    raise RuntimeError('Fresh startup failed: ' + process.stderr.read().decode(errors='replace')[-1200:])
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/login', timeout=1) as response:
                        body = response.read().decode()
                        ready = response.status == 200 and 'Khadang' in body
                    if ready:
                        break
                except OSError:
                    pass
                time.sleep(0.25)
            assert ready, 'Fresh password dashboard did not start'
        finally:
            process.terminate()
            process.communicate(timeout=15)
    finally:
        os.chdir(previous)
print('Fresh setup passed: private hash, no overwrite, no provider credentials, password dashboard starts.')
