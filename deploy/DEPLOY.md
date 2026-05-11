# Hostinger VPS deploy runbook

Target: one Hostinger **KVM 2** VPS (2 vCPU / 8 GB / 100 GB NVMe) running
Ubuntu 24.04, with `dgcomp run` firing on a 30-minute systemd timer.

End-to-end takes ~20 minutes the first time. Everything in `deploy/` is
idempotent — re-running it on the same box upgrades in place.

Nothing in `deploy/bootstrap.sh`, `dgcomp.service` or `dgcomp.timer` is
Hostinger-specific; any Ubuntu 24.04 host with root SSH access works.

---

## 0. Prerequisites (laptop side)

- Hostinger account with a VPS plan (sign up at <https://www.hostinger.com/vps-hosting>).
- An ed25519 SSH key (`~/.ssh/id_ed25519.pub`) you're happy to paste in.
- The two secrets:
  - `ANTHROPIC_API_KEY` (Claude Haiku validator)
  - `BUTTONDOWN_API_KEY` (from <https://buttondown.com/settings/programming>)
- Local `data/vocab.sqlite` is up to date (run `uv run dgcomp backfill --since
  <last_decision_date>` first if not).

## 1. Create the server (Hostinger hPanel)

1. In hPanel → **VPS** → **Setup**:
   - Plan: **KVM 2** (2 vCPU · 8 GB · 100 GB NVMe).
   - Datacenter: any EU location (Vilnius / Amsterdam / Paris).
   - OS: **Ubuntu 24.04 LTS**.
   - Authentication: paste your `~/.ssh/id_ed25519.pub` (or add it under
     **SSH Keys** first, then select it).
   - Hostname: `dgcomp-says-01`.
2. Hit **Setup VPS** and wait ~1–2 min for provisioning, then copy the IPv4
   from the VPS overview page.
3. (Optional) In **Backups & Snapshots**, enable weekly automatic backups.

## 2. Bootstrap (server side)

From your laptop:

```bash
ssh root@<IP> 'bash -s' < deploy/bootstrap.sh
```

This script:
- `apt upgrade` + installs `python3.12`, `git`, `uv`, `sqlite3`, etc.
- Creates the unprivileged `dgcomp` user, copies your authorized_keys to it.
- Clones this repo into `/home/dgcomp/DGCOMP-says` and runs `uv sync`.
- Installs `dgcomp.service` and `dgcomp.timer` into `/etc/systemd/system/`.
- Enables `unattended-upgrades`.

It does **not** start the timer — the bot still needs `.env` and the seeded DB.

## 3. Push the seeded SQLite

From your laptop, repo root:

```bash
./deploy/sync-db.sh dgcomp@<IP>
```

`rsync` over SSH; resumable, only transfers the delta on subsequent runs.

## 4. Drop `.env` on the box

```bash
ssh dgcomp@<IP>
cd ~/DGCOMP-says
cat > .env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...
BUTTONDOWN_API_KEY=...
EOF
chmod 600 .env
```

## 5. Smoke test

```bash
ssh dgcomp@<IP>
cd ~/DGCOMP-says
~/.local/bin/uv run dgcomp run --skip-post --verbose
```

Expect: a few EC search-API requests, then `ingested 0 new words` (or the
day's count if anything published).

## 6. Start the timer

```bash
ssh root@<IP>
systemctl enable --now dgcomp.timer
systemctl list-timers dgcomp.timer
journalctl -u dgcomp.service -f
```

`OnUnitActiveSec=2h` plus `Persistent=true` means the bot fires every two
hours and catches up missed ticks if the box reboots. Adjust to taste in
`/etc/systemd/system/dgcomp.timer` (and re-run `systemctl daemon-reload &&
systemctl restart dgcomp.timer`).

## 7. Lock down SSH (optional but recommended)

```bash
ssh root@<IP>
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh
# Reconnect as dgcomp@ from now on; root logins are disabled.
```

---

## Operations

### Updating the bot

```bash
ssh dgcomp@<IP>
cd ~/DGCOMP-says
git pull --ff-only
~/.local/bin/uv sync
# systemd picks up the new code on the next timer tick — no restart needed.
```

### Inspecting runs

```bash
ssh dgcomp@<IP>
journalctl --user -u dgcomp.service -n 200      # last 200 lines
journalctl -u dgcomp.service --since "1 hour ago"
systemctl list-timers dgcomp.timer              # next scheduled run
```

### Pulling the SQLite back to the laptop (e.g. weekly backup)

```bash
rsync -avh --progress \
  dgcomp@<IP>:DGCOMP-says/data/vocab.sqlite \
  data/vocab.sqlite
```

Hostinger's weekly snapshots (enabled in step 1) cover the host as a whole;
this gives you a second copy under your own control.
