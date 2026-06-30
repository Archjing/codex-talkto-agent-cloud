# Setup Assistant Guide

This guide is for Codex or another local assistant helping a user configure `codex-talkto-agent@cloud`.

## Minimal Questions

Ask only for values that cannot be safely inferred:

1. Remote mailbox rsync root.
   Example: `user@host:/home/user/codex-mailbox`
2. Remote agent ID.
   Example: `luke`, `claude`, `gemini`, `remote-agent`
3. Remote agent runtime.
   Example: `codex`, `claude`, `gemini`, `openclaw`, or `shell`

Use defaults unless the user asks otherwise:

- local mailbox: `~/.local/share/codex-talkto-agent-cloud/mailbox`
- local agent ID: `codex`
- thread ID: `default`
- archive retention: `14` days

## Command Pattern

Use this shell pattern to locate the installed CLI path without asking the user to inspect tables:

```bash
plugin_cli="$(python3 - <<'PY'
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
)"
"$plugin_cli" setup \
  --remote-rsync '<user@host:/path/to/mailbox>' \
  --peer-id '<remote-agent-id>' \
  --non-interactive
```

`setup` installs the short CLI entrypoint when possible, writes the config file, creates local mailbox folders, and runs local `doctor`.

Then send the remote bootstrap message. This is the handoff that tells the remote agent what to save and how to start its processing loop:

```bash
talkto-agent-cloud send-remote-setup \
  --agent-kind '<codex|claude|gemini|openclaw|shell>' \
  --sync
```

For `--agent-kind shell`, add a fixed remote command that receives a body-file path and prints a reply:

```bash
--agent-command '/path/to/remote-agent-command'
```

The `remote_setup` message body is a standard prompt for the remote agent. It attaches:

- `remote-agent.config.json`
- `talkto_agent_cloud.py`

Ask the user to paste or forward that setup prompt to the remote agent. The remote agent should save the attachments and start one of:

- `python3 talkto_agent_cloud.py --config remote-agent.config.json remote-run --once`
- `python3 talkto_agent_cloud.py --config remote-agent.config.json remote-run`
- a cron entry that runs `remote-run --once`
- a systemd service that runs `remote-run`

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

If local messages sync but the remote agent does not answer, check whether the outbound message has an ACK:

```bash
talkto-agent-cloud inbox --direction codex_to_<remote-agent-id> --all
```

No ACK usually means the remote processing loop is not running or is not reading the same mailbox path.

## Boundaries

- Do not edit shell startup files by default.
- Do not require `.env`.
- Do not require the user to locate the plugin directory manually; use `codex plugin list --json` or `setup` first.
- Do not store secrets in messages, attachments, or config.
- Do not use `rsync --delete`.
- Do not execute mailbox message content.
- Do not assume remote execution happens automatically after sync; a remote loop, cron, systemd service, or runtime integration must be configured.
