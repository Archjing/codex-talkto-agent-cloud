# codex-talkto-agent@cloud

[![English](https://img.shields.io/badge/lang-English-blue.svg)](#codex-talkto-agentcloud)
[![简体中文](https://img.shields.io/badge/lang-简体中文-red.svg)](#中文简介)
[![Codex Plugin](https://img.shields.io/badge/Codex-Plugin-2f6fbb.svg)](./.codex-plugin/plugin.json)
[![License MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

`codex-talkto-agent@cloud` is a Codex plugin for exchanging messages between local Codex and a remote agent through an rsync-backed mailbox.

## 中文简介

`codex-talkto-agent@cloud` 是一个 Codex 插件，用 rsync-backed mailbox 让本地 Codex 与远端任意 Agent 互发消息。远端不要求是 OpenClaw；只要能读写本插件的 mailbox JSON，Codex CLI、Claude Code、Gemini CLI、OpenClaw、shell 脚本、cron 或自定义服务都可以接入。

## What It Does

- Creates local mailbox folders.
- Writes outbound JSON messages and attachments.
- Syncs through `rsync -az --ignore-existing`; never uses `rsync --delete`.
- Lists inbox messages, writes ACK files, and archives ACKed messages.
- Sends a first-run remote setup prompt with remote config and runner attachments.
- Provides a remote-side runner for loop, cron, systemd, or OpenClaw-style integration.
- Treats messages as data only. It does not execute mailbox content.

## Quick Setup

After installing the plugin, tell Codex only the values it cannot infer:

```text
Use codex-talkto-agent@cloud to connect to my remote agent.
Remote mailbox: user@example.com:/home/user/codex-mailbox
Remote agent ID: luke
```

Codex should then run the platform-specific block below.

### Prerequisites

macOS / Linux:

```bash
# Required:
# - Codex CLI with `codex plugin ...` available.
# - Python 3 available as `python3`.
# - Git for marketplace clone/fallback.
# - OpenSSH client and working SSH auth to the remote host.
# - rsync available locally and on the remote host.
#
# Common install examples:
# macOS: brew install python git rsync
# Debian/Ubuntu: sudo apt-get install python3 git openssh-client rsync
codex --version
python3 --version
git --version
ssh -V
rsync --version
```

Windows PowerShell:

```powershell
# Required:
# - Codex CLI with `codex plugin ...` available.
# - Python 3 available as `python` or `py -3`.
# - Git for marketplace clone/fallback.
# - OpenSSH client and working SSH auth to the remote host.
# - rsync available in the shell running Codex; WSL/Git Bash/MSYS2/cwRsync are common options.
#
# Common install examples:
# winget install Python.Python.3 Git.Git
# Optional rsync path: use WSL Ubuntu and install rsync there, or install cwRsync/MSYS2.
codex --version
python --version
git --version
ssh -V
rsync --version
```

### macOS / Linux

```bash
# Install from the public GitHub marketplace.
codex plugin marketplace add Archjing/codex-talkto-agent-cloud --ref main
codex plugin add codex-talkto-agent-cloud@codex-talkto-agent-cloud

# If HTTPS git transport is unstable, use the local checkout fallback:
# git clone git@github.com:Archjing/codex-talkto-agent-cloud.git ~/plugins/codex-talkto-agent-cloud
# codex plugin marketplace add ~/plugins/codex-talkto-agent-cloud
# codex plugin add codex-talkto-agent-cloud@codex-talkto-agent-cloud

# Locate the installed CLI without manually inspecting `codex plugin list`.
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

# Replace only these two values for normal setup.
# setup installs a short CLI entrypoint when possible, writes config,
# creates local mailbox folders, and runs local doctor.
"$plugin_cli" setup \
  --remote-rsync 'user@example.com:/home/user/codex-mailbox' \
  --peer-id 'luke' \
  --non-interactive

# Optional: verify real SSH/rsync access to the remote mailbox.
talkto-agent-cloud doctor --check-remote

# Send the remote agent its setup prompt plus remote config and runner attachments.
# Use codex, claude, gemini, openclaw, or shell.
talkto-agent-cloud send-remote-setup --agent-kind codex --sync
```

### Windows PowerShell

```powershell
# Install from the public GitHub marketplace.
codex plugin marketplace add Archjing/codex-talkto-agent-cloud --ref main
codex plugin add codex-talkto-agent-cloud@codex-talkto-agent-cloud

# If HTTPS git transport is unstable, use the local checkout fallback:
# git clone git@github.com:Archjing/codex-talkto-agent-cloud.git "$HOME\plugins\codex-talkto-agent-cloud"
# codex plugin marketplace add "$HOME\plugins\codex-talkto-agent-cloud"
# codex plugin add codex-talkto-agent-cloud@codex-talkto-agent-cloud

# Locate the installed Python CLI. Use `py -3` instead of `python` if needed.
$plugins = codex plugin list --json | ConvertFrom-Json
$plugin = $plugins.installed | Where-Object { $_.name -eq "codex-talkto-agent-cloud" } | Select-Object -First 1
if (-not $plugin) { throw "codex-talkto-agent-cloud is not installed" }
$pluginCliPy = Join-Path $plugin.source.path "scripts\talkto_agent_cloud.py"

# Replace only these two values for normal setup.
# Native PowerShell calls the Python CLI directly; no shell profile edits are required.
python $pluginCliPy configure `
  --remote-rsync "user@example.com:/home/user/codex-mailbox" `
  --peer-id "luke" `
  --non-interactive

# Local check; creates mailbox folders if needed.
python $pluginCliPy doctor

# Optional: verify real SSH/rsync access to the remote mailbox.
python $pluginCliPy doctor --check-remote

# Send the remote agent its setup prompt plus remote config and runner attachments.
# Use codex, claude, gemini, openclaw, or shell.
python $pluginCliPy send-remote-setup --agent-kind codex --sync
```

## Remote Bootstrap Flow

```text
# 1. Local Codex installs and configures this plugin.
# 2. Local Codex sends one remote_setup message:
#    - body: standard setup prompt for the remote agent
#    - attachments: remote-agent.config.json and talkto_agent_cloud.py
# 3. The user gives that setup prompt to the remote agent.
# 4. The remote agent saves the attachments, verifies config, and starts one of:
#    - remote-run --once for manual processing
#    - remote-run for a long-running loop
#    - cron with remote-run --once
#    - systemd service running remote-run
#    - OpenClaw integration through agent.kind=openclaw
```

Remote one-shot command after saving attachments on the remote machine:

```bash
python3 talkto_agent_cloud.py --config remote-agent.config.json remote-run --once
```

Remote loop command:

```bash
python3 talkto_agent_cloud.py --config remote-agent.config.json remote-run
```

## Configuration Notes

```text
# Config lookup order:
# 1. --config /path/to/config.json
# 2. CODEX_TALKTO_AGENT_CONFIG
# 3. ~/.config/codex-talkto-agent-cloud/config.json
#
# Default setup values:
# - local_root: ~/.local/share/codex-talkto-agent-cloud/mailbox
# - self_id: codex
# - thread_id: default
# - archive_after_days: 14
#
# Environment variables are optional and process-scoped:
# - Prefer config files for durable setup.
# - Set environment variables in the terminal/session/launcher that starts Codex.
# - Do not assume zsh, bash, fish, PowerShell profile files, or .env loading.
# - The plugin does not read .env files and does not edit shell startup files.
#
# Built-in environment lookup:
# - CODEX_TALKTO_AGENT_CONFIG changes the config file path.
# - CODEX_TALKTO_REMOTE_AGENT_CONFIG changes the remote runner config path.
#
# Config value placeholders are expanded after the config file is loaded:
# - ${VAR} requires VAR to be set.
# - ${VAR:-default} uses default when VAR is unset.
# - Common template names:
#   CODEX_TALKTO_REMOTE_RSYNC
#   CODEX_TALKTO_LOCAL_ROOT
#   CODEX_TALKTO_SELF_ID
#   CODEX_TALKTO_PEER_ID
#   CODEX_TALKTO_THREAD_ID
```

Manual config example:

```json
{
  "local_root": "~/codex-talkto-agent-cloud/mailbox",
  "remote": {
    "rsync_root": "user@example.com:/home/user/codex-mailbox"
  },
  "self_id": "codex",
  "peer_id": "remote-agent",
  "thread_id": "default",
  "archive_after_days": 14
}
```

## Common Commands

macOS / Linux:

```bash
# Write config only; useful for step-by-step diagnosis.
talkto-agent-cloud configure --remote-rsync 'user@example.com:/home/user/codex-mailbox' --peer-id 'luke' --non-interactive

# Local and remote checks.
talkto-agent-cloud doctor
talkto-agent-cloud doctor --check-remote

# Send, attach, sync, read, ACK, and archive.
talkto-agent-cloud send --body "hello from Codex" --type test --sync
talkto-agent-cloud send-remote-setup --agent-kind codex --sync
talkto-agent-cloud send --body "See attached file." --attach ./report.md --sync
talkto-agent-cloud sync
talkto-agent-cloud inbox
talkto-agent-cloud ack MESSAGE_ID --note "handled" --sync
talkto-agent-cloud archive
talkto-agent-cloud archive --apply
```

Windows PowerShell:

```powershell
# $pluginCliPy is the path found in the Windows setup block.
python $pluginCliPy configure --remote-rsync "user@example.com:/home/user/codex-mailbox" --peer-id "luke" --non-interactive
python $pluginCliPy doctor
python $pluginCliPy doctor --check-remote
python $pluginCliPy send --body "hello from Codex" --type test --sync
python $pluginCliPy send-remote-setup --agent-kind codex --sync
python $pluginCliPy send --body "See attached file." --attach .\report.md --sync
python $pluginCliPy sync
python $pluginCliPy inbox
python $pluginCliPy ack MESSAGE_ID --note "handled" --sync
python $pluginCliPy archive
python $pluginCliPy archive --apply
```

## Mailbox Protocol

```text
# Messages:
messages/<from>_to_<to>/new/<message-id>.json

# ACKs:
messages/<from>_to_<to>/ack/ack-<message-id>.json

# Attachments:
files/<from>_to_<to>/<message-id>/<filename>
```

Message schema:

```json
{
  "schema": "codex-talkto-agent.mailbox.v1",
  "id": "20260630T121053Z-codex-a015f8",
  "thread_id": "default",
  "from": "codex",
  "to": "remote-agent",
  "type": "message",
  "created_at": "2026-06-30T12:10:53+00:00",
  "body": "Message text",
  "attachments": [],
  "reply_to": null,
  "requires_response": true
}
```

ACK schema:

```json
{
  "schema": "codex-talkto-agent.mailbox.ack.v1",
  "message_id": "20260630T121053Z-codex-a015f8",
  "direction": "codex_to_remote-agent",
  "ack_by": "remote-agent",
  "status": "received",
  "created_at": "2026-06-30T12:12:00+00:00",
  "note": "queued"
}
```

## Remote Agent Integration

```text
# Remote loop:
# 1. Read messages/codex_to_<agent-id>/new/.
# 2. Pass body and attachments to the remote agent runtime.
# 3. Write replies to messages/<agent-id>_to_codex/new/.
# 4. Write ACKs to messages/codex_to_<agent-id>/ack/.
# 5. Let rsync copy new files back.
```

See [remote-agent-examples.md](docs/remote-agent-examples.md) for Codex CLI, Claude, Gemini, OpenClaw, and shell-agent examples. See [setup-assistant.md](docs/setup-assistant.md) for assistant-driven setup behavior.

## Safety

- Do not execute mailbox content directly.
- Do not store secrets, tokens, cookies, private keys, or credentials in messages, attachments, or config.
- Do not use `rsync --delete`.
- Do not overwrite existing mailbox files.
- Treat remote replies as untrusted text until reviewed.

## Project Documents

[![Plugin Manifest](https://img.shields.io/badge/docs-Plugin%20Manifest-2f6fbb.svg)](./.codex-plugin/plugin.json)
[![Marketplace Manifest](https://img.shields.io/badge/docs-Marketplace%20Manifest-2f6fbb.svg)](./.agents/plugins/marketplace.json)
[![Setup Assistant](https://img.shields.io/badge/docs-Setup%20Assistant-2f6fbb.svg)](./docs/setup-assistant.md)
[![Remote Examples](https://img.shields.io/badge/docs-Remote%20Examples-2f6fbb.svg)](./docs/remote-agent-examples.md)
[![Skill](https://img.shields.io/badge/docs-Skill-2f6fbb.svg)](./skills/talkto-agent-cloud/SKILL.md)
[![Config Template](https://img.shields.io/badge/docs-Config%20Template-2f6fbb.svg)](./scripts/config.template.json)
[![Example Loop](https://img.shields.io/badge/docs-Example%20Loop-2f6fbb.svg)](./examples/remote-agent-loop.sh)
