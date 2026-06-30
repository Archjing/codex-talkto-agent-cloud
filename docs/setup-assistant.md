# Setup Assistant Guide

This guide is for Codex or another local assistant helping a user configure `codex-talkto-agent@cloud`.

## Minimal Questions

Ask only for values that cannot be safely inferred:

1. Remote mailbox rsync root.
   Example: `user@host:/home/user/codex-mailbox`
2. Remote agent ID.
   Example: `luke`, `claude`, `gemini`, `remote-agent`

Use defaults unless the user asks otherwise:

- local mailbox: `~/.local/share/codex-talkto-agent-cloud/mailbox`
- local agent ID: `codex`
- thread ID: `default`
- archive retention: `14` days

## Command Pattern

First locate the installed CLI path without asking the user to inspect tables:

```bash
python3 - <<'PY'
import json
import subprocess

payload = json.loads(subprocess.check_output(["codex", "plugin", "list", "--json"], text=True))
for item in payload.get("installed", []):
    if item.get("name") == "codex-talkto-agent-cloud":
        print(item["source"]["path"] + "/scripts/talkto-agent-cloud")
        break
else:
    raise SystemExit("codex-talkto-agent-cloud is not installed")
PY
```

Then run one setup command:

```bash
<plugin-dir>/scripts/talkto-agent-cloud setup \
  --remote-rsync '<user@host:/path/to/mailbox>' \
  --peer-id '<remote-agent-id>' \
  --non-interactive
```

`setup` installs the short CLI entrypoint when possible, writes the config file, creates local mailbox folders, and runs local `doctor`.

If the user gives overrides, add only the needed flags:

```bash
--self-id '<local-agent-id>'
--thread-id '<thread-id>'
--local-root '<local-mailbox-path>'
--archive-after-days 14
```

If `setup` reports that the bin directory is not on PATH, use the full path printed by that command for follow-up commands, or keep using `<plugin-dir>/scripts/talkto-agent-cloud`.

## Step-By-Step Fallback

Use the older split flow only when setup needs diagnosis:

```bash
<plugin-dir>/scripts/talkto-agent-cloud install-cli
talkto-agent-cloud configure \
  --remote-rsync '<user@host:/path/to/mailbox>' \
  --peer-id '<remote-agent-id>' \
  --non-interactive
talkto-agent-cloud doctor
```

## Verification

`setup` already runs local `doctor`. For a later local check, run:

```bash
talkto-agent-cloud doctor
```

Run the remote check only when the user wants SSH/rsync verification:

```bash
talkto-agent-cloud doctor --check-remote
```

## Boundaries

- Do not edit shell startup files by default.
- Do not require `.env`.
- Do not require the user to locate the plugin directory manually; use `codex plugin list --json` or `setup` first.
- Do not store secrets in messages, attachments, or config.
- Do not use `rsync --delete`.
- Do not execute mailbox message content.
