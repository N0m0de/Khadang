# Private server deployment

Use a dedicated directory, service account, configuration and database for your instance.
Do not run two polling processes for the same bot token. This example assumes the repository
and virtual environment are in `/opt/khadang` and private runtime files in `/var/lib/khadang`.
Adapt paths and ownership for your own server; no existing installation is modified by cloning.

1. Install Python 3.12+, Git and venv support using your distribution's package manager.
2. Create an unprivileged `khadang` service user and the two directories above. Clone the
   repository into `/opt/khadang`; create a venv and install with `pip install -e .`.
3. As that user, with working directory `/var/lib/khadang`, run
   `/opt/khadang/.venv/bin/python -m secretary.initialize`.
4. Protect `/var/lib/khadang` (mode 700) and `.env` (mode 600). Keep the source read-only
   for the service account after setup. Put custom prompts in this private working directory.
5. Install the example unit below as `khadang.service`, then `systemctl daemon-reload`
   and `systemctl enable --now khadang`. A deliberate dashboard restart exits the process;
   systemd starts it again. Keep backups of private data separately from Git.

```ini
[Unit]
Description=Khadang private Telegram assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=khadang
Group=khadang
WorkingDirectory=/var/lib/khadang
ExecStart=/opt/khadang/.venv/bin/python -m secretary
Restart=always
RestartSec=5
TimeoutStopSec=20
KillMode=control-group
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/khadang
StandardOutput=null
StandardError=null

[Install]
WantedBy=multi-user.target
```

Do not add a second `EnvironmentFile` with model/key settings: it would override edits
saved in the dashboard. The application loads the private working-directory `.env`.
Inspect `systemctl status khadang` for service state. Logs are disabled in this example
to avoid retaining accidental provider/transport details; temporarily enable local
diagnostics only if needed and never share raw logs without checking them.

## Open the dashboard from your computer

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:8780:127.0.0.1:8780 your-user@your-server
```

Keep that terminal open and visit http://127.0.0.1:8780/login. If the connection closes,
rerun the command. On Windows you can save your own command in a local `.cmd` file; never
put private key material in it. The assistant continues operating on the server when
your laptop is off; the tunnel is needed only to view the private dashboard.

Leave the dashboard bound to loopback. Do not open its port on the public firewall or
reuse somebody else's VPN profile, SSH key, bot token, or password.

## Independent receiver health check

For unattended deployments, supervise successful message reception as well as process
state. A temporary Telegram startup failure exits for systemd to retry; the internal
watchdog also sets a 30-second hard shutdown deadline. The separate check below catches
a hung event loop or a setup-only process with stale polling health.

Add `/etc/systemd/system/khadang-healthcheck.service`:

```ini
[Unit]
Description=Khadang receiver health check
After=khadang.service
[Service]
Type=oneshot
ExecStart=/opt/khadang/.venv/bin/python /opt/khadang/scripts/service_healthcheck.py --service khadang --db /var/lib/khadang/runtime/khadang.db
TimeoutStartSec=45
```

Add `/etc/systemd/system/khadang-healthcheck.timer`:

```ini
[Unit]
Description=Check Khadang receiver every minute
[Timer]
OnBootSec=2min
OnUnitActiveSec=60s
AccuracySec=5s
Unit=khadang-healthcheck.service
[Install]
WantedBy=timers.target
```

Adapt the database path if you changed `DB_PATH`. Then run `systemctl daemon-reload`
and `systemctl enable --now khadang-healthcheck.timer`. The checker requires service
administrator permissions to restart only the named service. It reads heartbeat metadata
only, not API keys or message content; it respects a manually stopped service and grants
three minutes for startup. A deliberately unconfigured installation is skipped.
