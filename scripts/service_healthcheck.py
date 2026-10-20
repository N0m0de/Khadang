"""External receiver watchdog. Run as a service administrator, never with provider keys."""
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import time


def needs_restart(mode, last_success, service_age, now):
    if mode == 'unconfigured' or service_age < 180:
        return False
    return not last_success or now - last_success > 240


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--service', default='khadang')
    parser.add_argument('--db', type=Path, required=True)
    args=parser.parse_args()
    if subprocess.run(['systemctl','is-active','--quiet',args.service]).returncode:
        return  # Respect an explicitly stopped service.
    value=subprocess.check_output(['systemctl','show',args.service,'-p','ActiveEnterTimestampMonotonic','--value'],text=True)
    service_age=float(Path('/proc/uptime').read_text().split()[0])-int(value.strip())/1_000_000
    mode, last_success=None,None
    try:
        with sqlite3.connect(f'file:{args.db}?mode=ro',uri=True,timeout=3) as connection:
            states=dict(connection.execute('SELECT key,value FROM bot_state WHERE key IN (?,?)',
                                           ('runtime_mode','telegram_polling_health')))
        mode=states.get('runtime_mode')
        last_success=json.loads(states.get('telegram_polling_health','{}')).get('last_success_at')
    except (OSError,sqlite3.Error,ValueError):
        pass
    if needs_restart(mode,last_success,service_age,time.time()):
        print('Receiver heartbeat stale; restarting configured service. No message content inspected.')
        subprocess.run(['systemctl','try-restart',args.service],check=True,timeout=40)


if __name__=='__main__':
    main()
