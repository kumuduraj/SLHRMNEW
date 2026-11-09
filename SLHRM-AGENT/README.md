# SLHRM biometric agent

Reads ZKTeco devices **read-only** (pyzk) and delivers every raw attendance record to SLHRM exactly once
(`slhrm.api.device_ingest` → Biometric Punch Log, unique `punch_key`). Design and failure analysis:
`~/cc-tmp/biometric_sync_analysis_20261109.md` (Phase 2.0).

## Device rules (hard)
- Only these pyzk calls: connect, get_serialnumber, get_firmware_version, get_device_name, get_platform,
  get_mac, get_time, read_sizes, get_users, get_attendance, disconnect (`ReadOnlyDevice` refuses others;
  pyzk's buffered reads also send CMD_FREE_DATA, which only releases the device's transfer buffer).
- Never clear, write, disable/enable, set the time, restart, live-capture.
- One connection per device at a time (`run` takes a lock), timeout 10 s, `ommit_ping`.
- At most 2 connect attempts per device per command (`probe`: password 0, then 111111; TCP, UDP if the TCP
  port is closed / fails). No retry loops.

## Zero loss / zero duplicates
- Local SQLite queue (`db_path`, WAL, synchronous=FULL). Each pull inserts-or-ignores the WHOLE device log
  by `serial|device user id|YYYY-MM-DD HH:MM:SS` — clock corrections or late records can't be skipped.
- A record is confirmed only by its server result (`inserted`, `duplicate`, `unknown_employee` — unknown
  users are stored server-side as Unmatched). Errors stay queued (`failed`, retried next run; `held` after
  20 attempts, `push --retry-held`). Server down → the run stops pushing; nothing is lost.
- Serial check: a device whose serial differs from the config is not read (IP reassigned?).
- Heartbeat per device → Biometric Device health (clock drift, sizes, queue depth, last error).

## Install (VPS: /home/rajerp/slhrm-agent)
    python3 -m venv ~/slhrm-agent/venv && ~/slhrm-agent/venv/bin/pip install -r SLHRM-AGENT/requirements.txt
    cp SLHRM-AGENT/config.example.json ~/slhrm-agent/config.json && chmod 600 ~/slhrm-agent/config.json
    A=~/GILLSHR/apps/slhrm/SLHRM-AGENT/slhrm_agent.py; PY=~/slhrm-agent/venv/bin/python
    $PY $A tcpcheck | probe --ip IP | info --device N | users --device N --csv F | pull --device N --dry-run --since 2026-10-01
    $PY $A run          # pull + heartbeat + push (needs api_key = SLHRM Settings device_api_key)
    $PY $A status
The config must be chmod 600 (the agent refuses otherwise). The device must exist in Biometric Device
(name = serial) before records are accepted.

## Scheduler (NOT enabled until Raj approves the backfill)
    # crontab -e (rajerp):
    # */5 * * * * /home/rajerp/slhrm-agent/venv/bin/python /home/rajerp/GILLSHR/apps/slhrm/SLHRM-AGENT/slhrm_agent.py --config /home/rajerp/slhrm-agent/config.json run >/dev/null 2>&1

## Tests
    python3 -m unittest discover -s SLHRM-AGENT/tests -v
