"""Run synthetic checks as separate processes so test configuration cannot leak between suites."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
checks = ['initialize', 'polling', 'api_limits', 'core', 'openai', 'qwen', 'private', 'dashboard', 'learning', 'export', 'attribution', 'reporting', 'followups']
for check in checks:
    env = dict(os.environ, OWNER_FIRST_NAME='Alex', REPORTS_ENABLED='true', URGENT_ALERTS_ENABLED='true')
    # Never inherit user credentials into offline suites.
    for key in ('OPENAI_API_KEY', 'TG_BOT_TOKEN', 'OPENROUTER_API_KEY', 'ANTHROPIC_API_KEY', 'SECRETORY_PASSWORD_HASH', 'SECRETORY_PRIVATE_AUTH'):
        env.pop(key, None)
    with tempfile.TemporaryDirectory() as temporary:
        env['SECRETORY_CONFIG_FILE'] = str(Path(temporary) / '.env')
        subprocess.run([sys.executable, str(root / 'scripts' / f'smoke_{check}.py')],
                       cwd=temporary, env=env, check=True, timeout=120)
print('All offline checks passed.')
