# Deploying the EOD-only terminal to a cloud VPS

Target: a small always-on Linux VPS running the nightly EOD pipeline and
serving the baked HUD — reachable only from your own devices over
[Tailscale](https://tailscale.com), never the public internet. No live
broker connection is needed (the Fyers/live layer is archived).

Recommended: Hetzner CX22 (~€4/mo, Ubuntu 24.04) or equivalent. Any small
Debian/Ubuntu VPS works the same way.

---

## 1. Provision the box

Spin up the VPS, SSH in, and do basic hardening (this is on you / your
provider's image — not automated here): a non-root sudo user, SSH key auth,
`ufw` with only SSH allowed inbound (Tailscale doesn't need any inbound port
open — it's outbound-initiated).

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git
```

## 2. Install Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Follow the printed auth URL to join the VPS to your tailnet. Note the
Tailscale hostname it's assigned (`tailscale status`) — that's how you'll
reach the HUD, e.g. `http://vanguard-vps:8787` once step 5 is done, no
public domain or TLS cert needed.

## 3. Clone the repo and install deps

```bash
sudo mkdir -p /opt/vanguard && sudo chown $USER:$USER /opt/vanguard
git clone <your-repo-url> /opt/vanguard
cd /opt/vanguard
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

Use `./venv/bin/python3` for anything you run manually on the box (`./venv/bin/python3 scripts/build_hud.py`, etc). Ubuntu 24.04 blocks installing into the system Python directly (PEP 668) — a venv sidesteps that instead of overriding it with `--break-system-packages`, which risks conflicting with apt-managed packages.

## 4. Secrets — `.env`

Copy your local `.env` to the VPS **out of band** (scp over the Tailscale
network, never through git):

```bash
scp .env <vps-tailscale-hostname>:/opt/vanguard/.env
```

Then add the Telegram alert credentials (see §6) to that same `.env`:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

`chmod 600 /opt/vanguard/.env` — restrict to the owning user.

## 5. Install the systemd units

```bash
sudo cp deploy/vanguard-nightly.service deploy/vanguard-nightly.timer \
        deploy/vanguard-serve.service /etc/systemd/system/
sudo systemctl daemon-reload

# Nightly EOD sync — replaces the macOS launchd plist
sudo systemctl enable --now vanguard-nightly.timer

# HUD server — always-on, auto-restarts on crash/reboot
sudo systemctl enable --now vanguard-serve.service
```

Verify:

```bash
systemctl status vanguard-nightly.timer vanguard-serve.service
sudo systemctl start vanguard-nightly.service   # trigger one run immediately, don't wait for the window
journalctl -u vanguard-nightly.service -f
```

If your VPS's system clock isn't already IST, either
`sudo timedatectl set-timezone Asia/Kolkata` or edit the `OnCalendar=` lines
in `vanguard-nightly.timer` to match your box's timezone before enabling it
— the pipeline itself only cares about IST market hours.

## 6. Telegram alerts

1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` →
   follow the prompts → copy the bot token it gives you.
2. Message your new bot anything (so it can see your chat), then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and read
   `"chat":{"id": ...}` — that's your `TELEGRAM_CHAT_ID`.
3. Put both in `/opt/vanguard/.env` (step 4).

`scripts/notify_telegram.py` is already wired into `nightly.sh`'s existing
failure branches (bhavcopy never published by 21:00, `poll_eod.py` crash,
post-compile test failure, HUD parity mismatch) — nothing else to connect.
Test it directly:

```bash
./venv/bin/python3 scripts/notify_telegram.py "test alert from vanguard VPS"
```

## 7. Reach the HUD only over Tailscale

`vanguard/config/paths.py` binds the server to `127.0.0.1` by design — it
is never reachable from the VPS's public interface, with or without a
firewall. Expose it to your *other* Tailscale devices with:

```bash
sudo tailscale serve --bg 8787
```

This proxies the loopback port onto the tailnet only (HTTPS, via
Tailscale's own cert) — no public port is ever opened. From your phone/
laptop (also on the tailnet), open `https://<vps-tailscale-hostname>.<tailnet>.ts.net`.

## 8. Data durability (do before you trust this as your only copy)

`data/compiled/`, `vanguard.duckdb`, and `data/raw/` live only on this VPS's
disk (gitignored, never pushed). Add a periodic off-box backup once you're
comfortable with the setup — e.g. a weekly `rclone sync` of `data/compiled/`
to Backblaze B2 or S3. Not wired up yet; flag if you want this built next.

## 9. Deploying code changes

Simplest path, matches "just me" exposure: `ssh` in and `git pull` inside
`/opt/vanguard`, restart `vanguard-serve.service` if `vanguard/serve/` or
its dependents changed. A GitHub Action to automate this over Tailscale SSH
is a reasonable next step once the manual flow feels routine — not built
yet, ask if you want it.
