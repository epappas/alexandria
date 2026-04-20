# Mobile vault via GitHub

Make your alexandria knowledge base portable (read on any device) and
lightly writable from mobile (append URLs you want ingested later) using
nothing more than a private GitHub repository. No Obsidian, no Syncthing,
no extra daemons on your phone.

## Architecture

One private GitHub repo with a three-layer layout produced by
`alxia export --format github`:

```
alexandria-vault/              (private GitHub repo)
├── .alexandria/               canonical backup — raw/ + wiki/ in native form
├── wiki/                      human-readable projection
│   ├── README.md              topic index
│   └── <topic>/
│       ├── README.md          page list with titles + previews
│       └── <title-slug>.md
├── journal/                   chronological activity log
│   ├── README.md
│   └── YYYY-MM.md             per-month ingest entries
├── inbox.md                   you append URLs here from your phone
└── inbox-archive.md           ingested URLs, kept for history
```

The three generated layers serve distinct purposes:

- **`.alexandria/`** is the disaster-recovery artifact. Lose your
  desktop, clone this repo, copy `.alexandria/raw/` and
  `.alexandria/wiki/` back into `~/.alexandria/workspaces/<slug>/`, run
  `alxia reindex --rebuild-beliefs`, and the knowledge base is whole.
  SQLite is not committed (it regenerates and would cause binary churn).
- **`wiki/`** is what you read. Title-based filenames, per-folder
  READMEs, resolved footnote links, deduplicated citations.
- **`journal/`** is the "what did past-me add" timeline. Every ingest
  lands as a dated entry with links into `wiki/` and `.alexandria/raw/`.

Two independent loops run on your desktop:

1. **Capture loop** — phone edits `inbox.md` on GitHub → desktop pulls →
   ingests URLs → archives them → commits the cleared inbox back.
2. **Publish loop** — alexandria wiki changes (from ingests or any other
   write) → desktop re-exports to `wiki/` → commits + pushes.

Both loops live in a single sync script run on a timer.

## Honest tradeoffs

| | Syncthing | Git + GitHub |
|---|---|---|
| Mobile → desktop latency | Seconds | Minutes (sync timer cadence) |
| Privacy | Peer-to-peer, files never leave your devices | Private repo, files live on GitHub |
| Version history | None by default | Full git log |
| Mobile reading UX | Requires Obsidian or a file viewer | Native GitHub rendering in browser or app |
| Mobile writing UX | Save in Obsidian, done | Edit `inbox.md` via GitHub mobile (4 taps) |
| Cost | Free | Free for private repos |

If privacy from third parties is critical, prefer Syncthing. If you want
version history and mobile reading without installing anything, use this
guide.

## Desktop setup

### 1. Create the private repo

```bash
gh repo create alexandria-vault --private \
  --description "Alexandria knowledge base mirror"
```

Verify privacy immediately — a public repo here would leak your entire
knowledge base:

```bash
gh repo view alexandria-vault --json visibility
```

### 2. Initialize and seed locally

```bash
VAULT=~/alexandria-vault
mkdir -p "$VAULT"
cd "$VAULT"

git init
git branch -M main
git remote add origin git@github.com:"$(gh api user -q .login)"/alexandria-vault.git

# seed: first export + empty inbox
alxia export . --format github -w global
cat > inbox.md <<'EOF'
# Inbox

Append URLs below, one per line. The desktop sync job ingests them and
archives the entries to `inbox-archive.md`.
EOF

git add .
git commit -m "seed"
git push -u origin main
```

### 3. The sync script

A production-ready version ships in the alexandria repo — copy from
there rather than hand-typing:

```bash
# assuming you have the alexandria source checked out
cp /path/to/alexandria/scripts/vault/alexandria-vault-sync \
   ~/bin/alexandria-vault-sync
chmod +x ~/bin/alexandria-vault-sync
```

Or, if you prefer to hand-author, the full script looks like this
(reads `ALEXANDRIA_VAULT`, `ALEXANDRIA_VAULT_WORKSPACE`, and `ALXIA`
env vars with sensible defaults):

```bash
#!/usr/bin/env bash
set -euo pipefail

VAULT="$HOME/alexandria-vault"
cd "$VAULT"

# 1. pull any phone-side appends to inbox.md
git pull --rebase --autostash

# 2. extract URLs from inbox.md and ingest each
INBOX="$VAULT/inbox.md"
ARCHIVE="$VAULT/inbox-archive.md"
URL_LIST=$(mktemp)

grep -oE 'https?://[^ )]+' "$INBOX" > "$URL_LIST" || true

if [ -s "$URL_LIST" ]; then
  while IFS= read -r url; do
    echo ">> ingesting $url"
    if alxia ingest "$url" -w global; then
      echo "- $(date -u +%Y-%m-%d) $url" >> "$ARCHIVE"
    else
      echo "- $(date -u +%Y-%m-%d) FAILED $url" >> "$ARCHIVE"
    fi
  done < "$URL_LIST"

  # rewrite inbox to its clean baseline
  cat > "$INBOX" <<'EOF'
# Inbox

Append URLs below, one per line. The desktop sync job ingests them and
archives the entries to `inbox-archive.md`.
EOF
fi
rm -f "$URL_LIST"

# 3. refresh the three-layer vault (wiki/ + journal/ + .alexandria/ backup)
alxia export "$VAULT" --format github -w global

# 4. commit + push if anything changed
if ! git diff --quiet || ! git diff --cached --quiet; then
  git add -A
  git commit -m "sync: $(date -u +%Y-%m-%dT%H:%MZ)"
  git push origin main
fi
```

```bash
chmod +x ~/bin/alexandria-vault-sync
```

Smoke test it manually before wiring up the timer:

```bash
~/bin/alexandria-vault-sync
```

### 4. Systemd timer

Two unit files and one enable:

```ini
# ~/.config/systemd/user/alexandria-vault-sync.service
[Unit]
Description=Alexandria vault sync

[Service]
Type=oneshot
ExecStart=%h/bin/alexandria-vault-sync
```

```ini
# ~/.config/systemd/user/alexandria-vault-sync.timer
[Unit]
Description=Sync every 10 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now alexandria-vault-sync.timer
systemctl --user list-timers | grep alexandria     # confirm
```

Follow logs with:

```bash
journalctl --user -u alexandria-vault-sync -f
```

## Phone usage (zero install)

### Reading

Open the repo in a mobile browser or the GitHub mobile app. GitHub
renders markdown natively, including the cross-links between wiki
pages. Search works within the repo. No app install required beyond the
GitHub app if you want it.

### Capturing a URL

Using the GitHub mobile app:

1. Open `alexandria-vault` → `inbox.md`.
2. Tap the pencil icon (top right).
3. Paste the URL on a new line.
4. Tap ✓ → "Commit directly to main."

Within the sync cadence (default 10 minutes) the desktop ingests the
URL, archives it, and pushes the cleared inbox back.

### Faster capture (optional, install-free extensions)

If the 4-tap flow feels slow once you're using it regularly:

- **iOS**: build a Shortcut that uses the GitHub API
  (`PUT /repos/:owner/:repo/contents/inbox.md`) to append a URL and
  commit. Put it in the share sheet — one tap from any browser.
- **Android**: the HTTP Shortcuts app can do the same.

Skip until the base flow feels slow.

## Verifying the loop

1. From the phone, edit `inbox.md`, add a URL, commit.
2. On desktop, trigger a sync (or wait): `~/bin/alexandria-vault-sync`.
3. Inspect `inbox-archive.md` — your URL should appear as an ingested
   entry.
4. Confirm ingestion in the knowledge base:

```bash
alxia beliefs list -w global --limit 5
```

Beliefs extracted from your shared URL should appear.

## Caveats to know up front

- **Private repo is non-negotiable.** Anything else leaks your wiki to
  the public internet.
- **`wiki/` is overwritten every sync.** Only `inbox.md` and
  `inbox-archive.md` are safe to hand-edit. Don't edit wiki pages on
  GitHub expecting them to survive the next export.
- **Latency matches the timer.** Lower `OnUnitActiveSec` if you want
  tighter loops; raise it if git push noise bothers you.
- **Push auth on the timer.** The systemd service needs the same SSH
  agent or credential helper your shell uses. Verify by running the
  script once manually before enabling the timer.
- **Credential scope for mobile**: if you ever automate capture from
  mobile via the API, use a fine-grained personal access token scoped
  only to this one repo. Do not put a full-access token on a phone.
