# Mobile vault via GitHub — scripts

Shipped scripts that implement the pattern documented in
[`docs/guides/mobile_vault_github.md`](../../docs/guides/mobile_vault_github.md).

## Why this exists

alexandria is local-first and headless. Reading your knowledge base on a
phone and capturing URLs while away from keyboard requires an out-of-band
surface. These scripts turn a private GitHub repo into that surface:

- Phone reads rendered markdown in the GitHub app or browser.
- Phone appends URLs to `inbox.md` via GitHub's in-app file editor.
- Desktop periodically pulls, ingests URLs, re-exports the wiki, and
  pushes.

This keeps the wiki canonical on your desktop while giving you a
portable mirror that works on any device without installing Obsidian,
Syncthing, or anything else on the phone.

## Files

| File | Purpose | Install location |
|------|---------|------------------|
| `alexandria-vault-sync` | The loop: pull → ingest inbox URLs → export → commit → push | `~/bin/alexandria-vault-sync` |
| `alexandria-vault-sync.service` | Systemd user service, fires the script | `~/.config/systemd/user/alexandria-vault-sync.service` |
| `alexandria-vault-sync.timer` | Systemd user timer, runs the service every 10 min | `~/.config/systemd/user/alexandria-vault-sync.timer` |

## Prerequisites

1. A private GitHub repo that will hold your vault
   (`gh repo create <name> --private`).
2. A local clone of that repo at the path you'll point the script to
   (default: `~/knowledgebase`).
3. alexandria installed and initialized (`alxia init`, workspace
   populated).
4. Your SSH key or credential helper configured for GitHub push access.
5. `commit.gpgsign=true` (or false) set the way you want — the script
   respects whatever your git config says. It never bypasses signing.

## One-time setup

```bash
# 1. copy the loop script
mkdir -p ~/bin
cp scripts/vault/alexandria-vault-sync ~/bin/
chmod +x ~/bin/alexandria-vault-sync

# 2. copy the systemd units
mkdir -p ~/.config/systemd/user
cp scripts/vault/alexandria-vault-sync.service ~/.config/systemd/user/
cp scripts/vault/alexandria-vault-sync.timer   ~/.config/systemd/user/

# 3. seed the vault (first export + inbox)
VAULT=~/knowledgebase
alxia export "$VAULT" --format markdown -w global
cat > "$VAULT/inbox.md" <<'EOF'
# Inbox

Append URLs below, one per line. The desktop sync job ingests them and
archives the entries to `inbox-archive.md`.
EOF
cd "$VAULT" && git add -A && git commit -m "seed" && git push -u origin main

# 4. smoke-test the script before enabling the timer
~/bin/alexandria-vault-sync

# 5. enable the timer
systemctl --user daemon-reload
systemctl --user enable --now alexandria-vault-sync.timer
```

## Configuration

The script reads three environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `ALEXANDRIA_VAULT` | `$HOME/knowledgebase` | Path to your git-backed vault directory |
| `ALEXANDRIA_VAULT_WORKSPACE` | `global` | Which alexandria workspace to export |
| `ALXIA` | `$HOME/.local/bin/alxia` | Path to the alexandria CLI |

Set them in the systemd unit (`Environment=` directives in the
`.service` file) if your paths differ from the defaults.

## Operating

```bash
# manual run (does not affect the timer)
systemctl --user start alexandria-vault-sync

# follow what it's doing
journalctl --user -u alexandria-vault-sync -f

# check next scheduled fire
systemctl --user list-timers alexandria-vault-sync.timer

# stop the loop entirely
systemctl --user disable --now alexandria-vault-sync.timer
```

To change cadence: edit `OnUnitActiveSec=` in
`alexandria-vault-sync.timer`, then
`systemctl --user daemon-reload && systemctl --user restart alexandria-vault-sync.timer`.

## What the script does on each run

1. `git pull --rebase --autostash` — pulls any phone-side appends to
   `inbox.md`.
2. Greps `https?://` URLs out of `inbox.md`.
3. For each URL: `alxia ingest "$url"`; append result to
   `inbox-archive.md` (success or `FAILED`).
4. Rewrites `inbox.md` to its clean baseline (header only).
5. `alxia export` — refreshes every topic folder in the vault.
6. If anything changed: `git add -A && git commit -m "sync: <ts>" && git push`.

## Caveats

- **Wiki files are overwritten every run.** Only `inbox.md` and
  `inbox-archive.md` are hand-writable. Anything else you edit in the
  vault will be clobbered on the next sync.
- **The repo must be private.** Your knowledge base ends up on GitHub;
  a public repo leaks everything. Verify with
  `gh repo view <repo> --json visibility`.
- **Commits are signed if your config says so.** The script never
  passes `-c commit.gpgsign=false` or `--no-gpg-sign`. If gpg signing
  fails (agent locked, no tty), the commit will fail and the script
  exits non-zero — fix the signing environment rather than bypassing.
- **Latency matches the timer.** Default 10 min phone → wiki. Lower for
  tighter loops; raise if the commit noise on GitHub bothers you.
