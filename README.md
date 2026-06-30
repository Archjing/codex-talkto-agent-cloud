# codex-talkto-agent@cloud

[![English](https://img.shields.io/badge/lang-English-blue.svg)](#codex-talkto-agentcloud)
[![简体中文](https://img.shields.io/badge/lang-简体中文-red.svg)](#中文简介)
[![Codex Plugin](https://img.shields.io/badge/Codex-Plugin-2f6fbb.svg)](./.codex-plugin/plugin.json)
[![License MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

`codex-talkto-agent@cloud` is a Codex plugin for exchanging messages between local Codex and a remote agent through an rsync-backed mailbox.

## 中文简介

`codex-talkto-agent@cloud` 是一个 Codex 插件，用 rsync-backed mailbox 让本地 Codex 与远端任意 Agent 互发消息。

远端不需要是 OpenClaw。只要能读写本插件定义的 mailbox JSON 文件，Codex CLI、Claude Code、Gemini CLI、OpenClaw、shell 脚本、cron 任务或自定义服务都可以参与协作。

## Overview

The remote side does not need to be OpenClaw. Any agent runtime can participate if it can read and write JSON files in the mailbox format. Examples include Codex CLI, Claude Code, Gemini CLI, OpenClaw, shell scripts, cron jobs, or a custom service.

## What This Plugin Does

- Creates local mailbox folders.
- Writes outbound JSON messages from Codex to a remote agent.
- Syncs messages, attachments, and ACK files through `rsync -az --ignore-existing`.
- Lists inbound messages from the remote agent.
- Writes ACK files for handled messages.
- Archives ACKed messages after a retention window.

It does not execute mailbox content. Messages are data, not commands.

## Install

This repository is both:

- a standard Codex plugin directory, and
- a Codex marketplace root through `.agents/plugins/marketplace.json`.

### Install from GitHub

Add this repository as a Codex marketplace:

```bash
codex plugin marketplace add Archjing/codex-talkto-agent-cloud --ref main
```

Install the plugin from that marketplace:

```bash
codex plugin add codex-talkto-agent-cloud@codex-talkto-agent-cloud
```

Verify that Codex sees it:

```bash
codex plugin list --json
```

If the GitHub marketplace add step fails because your local HTTPS git transport is unstable, clone the repository first and add the local checkout instead:

```bash
git clone git@github.com:Archjing/codex-talkto-agent-cloud.git ~/plugins/codex-talkto-agent-cloud
codex plugin marketplace add ~/plugins/codex-talkto-agent-cloud
codex plugin add codex-talkto-agent-cloud@codex-talkto-agent-cloud
```

Open a new Codex session after installing or upgrading the plugin so the bundled skill instructions are loaded into that session.

中文提示：这个插件不是 `pip install` 或 `npm install` 包。它先作为 Codex marketplace 加入，再通过 `codex plugin add` 安装。

### Locate The CLI

The executable script lives inside the installed plugin directory:

```text
<plugin-dir>/scripts/talkto-agent-cloud
```

If you cloned the repository yourself, `<plugin-dir>` is the checkout path:

```bash
cd ~/plugins/codex-talkto-agent-cloud
scripts/talkto-agent-cloud --help
```

If you installed only through `codex plugin add`, Codex can locate the script path automatically with:

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

Example:

```bash
/path/from/codex-plugin-list/scripts/talkto-agent-cloud --help
```

Manual fallback: `codex plugin list` also prints a table containing the installed plugin path.

For shorter commands, install a user-level command entrypoint:

```bash
/path/from/codex-plugin-list/scripts/talkto-agent-cloud install-cli
```

This creates:

```text
~/.local/bin/talkto-agent-cloud
```

It does not edit `.zshrc`, `.bashrc`, fish config, PowerShell profiles, or any other shell startup file. If `~/.local/bin` is not on your PATH, the command prints the full path you can use immediately.

You can also choose another directory:

```bash
/path/from/codex-plugin-list/scripts/talkto-agent-cloud install-cli --bin-dir ~/bin
```

The rest of this README uses `talkto-agent-cloud` for readability. If the short command is not on PATH, replace it with `<plugin-dir>/scripts/talkto-agent-cloud` or the full path printed by `install-cli`.

### Local Development Install

Clone the repository:

```bash
git clone https://github.com/Archjing/codex-talkto-agent-cloud.git ~/plugins/codex-talkto-agent-cloud
cd ~/plugins/codex-talkto-agent-cloud
```

Add the local checkout as a marketplace:

```bash
codex plugin marketplace add ~/plugins/codex-talkto-agent-cloud
codex plugin add codex-talkto-agent-cloud@codex-talkto-agent-cloud
```

If you already maintain a personal marketplace at `~/.agents/plugins/marketplace.json`, you can instead add an entry pointing to `~/plugins/codex-talkto-agent-cloud`.

## Configure

The plugin runtime is config-driven. Installing the plugin does not configure your remote server, mailbox path, or agent IDs.

The easiest path is to let Codex collect the key values from you and run `setup`.

### Natural Language Setup

After installing the plugin, tell Codex something like:

```text
Use codex-talkto-agent@cloud to connect to my remote agent.
Remote mailbox: user@example.com:/home/user/codex-mailbox
Remote agent ID: luke
```

Codex should run one setup command. If the short command is not available yet, Codex should locate the installed script path using `codex plugin list --json` and call it directly:

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
  --remote-rsync 'user@example.com:/home/user/codex-mailbox' \
  --peer-id 'luke' \
  --non-interactive
```

This installs the short command when possible, writes a ready-to-use config file, creates the local mailbox folders, and runs a local `doctor` check.

The config file is written at:

```text
~/.config/codex-talkto-agent-cloud/config.json
```

Default values:

- local mailbox: `~/.local/share/codex-talkto-agent-cloud/mailbox`
- local agent ID: `codex`
- thread ID: `default`
- archive retention: `14` days

You can override them when needed:

```bash
talkto-agent-cloud setup \
  --remote-rsync 'user@example.com:/home/user/codex-mailbox' \
  --peer-id 'luke' \
  --self-id 'codex-laptop' \
  --thread-id 'ops' \
  --local-root '~/codex-mailbox' \
  --non-interactive
```

Run a local configuration check:

```bash
talkto-agent-cloud doctor
```

Run a remote dry-run sync check:

```bash
talkto-agent-cloud doctor --check-remote
```

中文提示：正常使用不需要编辑 shell 启动文件，也不需要手写环境变量。优先让 Codex 调用 `setup` 一次完成命令入口、JSON 配置和本地检查。

### Step-By-Step Setup

If you want to run each step separately:

```bash
<plugin-dir>/scripts/talkto-agent-cloud install-cli
talkto-agent-cloud configure \
  --remote-rsync 'user@example.com:/home/user/codex-mailbox' \
  --peer-id 'luke' \
  --non-interactive
talkto-agent-cloud doctor
```

### Config Lookup

The bundled CLI loads configuration in this order:

1. `--config /path/to/config.json`
2. `CODEX_TALKTO_AGENT_CONFIG`
3. `~/.config/codex-talkto-agent-cloud/config.json`

Important: `--config` is a global option and must appear before the subcommand:

```bash
talkto-agent-cloud --config ./config.local.json sync --dry-run
```

### Manual Template Mode

If you prefer to edit JSON by hand, create the default config template:

```bash
talkto-agent-cloud init-config
```

This writes:

```text
~/.config/codex-talkto-agent-cloud/config.json
```

The template uses environment placeholders:

```json
{
  "local_root": "${CODEX_TALKTO_LOCAL_ROOT:-~/codex-talkto-agent-cloud/mailbox}",
  "remote": {
    "rsync_root": "${CODEX_TALKTO_REMOTE_RSYNC}"
  },
  "self_id": "${CODEX_TALKTO_SELF_ID:-codex}",
  "peer_id": "${CODEX_TALKTO_PEER_ID:-remote-agent}",
  "thread_id": "${CODEX_TALKTO_THREAD_ID:-default}",
  "archive_after_days": 14
}
```

### Optional Environment Variables

Environment variables are optional. They are useful when you want one config file to work across different machines.

The CLI expands environment variables after reading the JSON config file:

- `${VAR}` requires `VAR` to be set. If it is missing, the command exits with an error.
- `${VAR:-default}` uses `default` when `VAR` is unset.
- `.env` files are not loaded automatically. If you use one, source it before running the CLI.

For example, in the current shell session:

```bash
export CODEX_TALKTO_REMOTE_RSYNC='user@example.com:/home/user/codex-mailbox'
export CODEX_TALKTO_LOCAL_ROOT="$HOME/codex-talkto-agent-cloud/mailbox"
export CODEX_TALKTO_SELF_ID='codex'
export CODEX_TALKTO_PEER_ID='remote-agent'
export CODEX_TALKTO_THREAD_ID='default'
```

If you choose to persist environment variables, put them wherever your own shell or launcher already loads environment settings. This plugin does not assume zsh, bash, fish, PowerShell, or any specific terminal.

Codex Desktop note: environment variables are inherited from the process that launches the command. Already-running Codex sessions may not see variables added later. For the simplest setup, prefer `setup`, which writes concrete JSON values and does not depend on shell startup behavior.

中文提示：插件不会自己读取 `.env`。它只读取当前进程环境变量，或者读取 `--config` / `CODEX_TALKTO_AGENT_CONFIG` 指向的 JSON 配置文件。

### Config Without Environment Variables

You can also write concrete values directly in the config file:

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

Do not put secrets, tokens, cookies, private keys, or passwords in this config. Use normal SSH key management for rsync access.

### Configuration Checklist

Before sending real messages, verify:

- `rsync` is installed locally.
- SSH access to `user@example.com` works.
- The remote mailbox parent directory exists and is writable.
- `remote.rsync_root` points to the remote mailbox root, not to a single message folder.
- `self_id` and `peer_id` differ.

Run a local check:

```bash
talkto-agent-cloud doctor
```

Run a remote dry-run sync:

```bash
talkto-agent-cloud doctor --check-remote
```

Send a test message:

```bash
talkto-agent-cloud send --body "hello from Codex" --type test --sync
```

Read replies:

```bash
talkto-agent-cloud sync
talkto-agent-cloud inbox
```

## Local Codex Commands

Send a message and sync it to the remote mailbox:

```bash
talkto-agent-cloud send --body "Please check the nginx redirect." --type ops_request --sync
```

Send with an attachment:

```bash
talkto-agent-cloud send --body "See attached file." --attach ./report.md --sync
```

Pull remote replies and list unacked inbox messages:

```bash
talkto-agent-cloud sync
talkto-agent-cloud inbox
```

ACK a received message and sync the ACK:

```bash
talkto-agent-cloud ack MESSAGE_ID --note "handled" --sync
```

Archive old ACKed messages:

```bash
talkto-agent-cloud archive
talkto-agent-cloud archive --apply
```

## Mailbox Protocol

Messages live under:

```text
messages/<from>_to_<to>/new/<message-id>.json
```

ACKs live under:

```text
messages/<from>_to_<to>/ack/ack-<message-id>.json
```

Attachments live under:

```text
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

The remote agent only needs to share the same mailbox directory and write messages back using the same schema.

Typical remote loop:

1. Read unacked files from `messages/codex_to_<agent-id>/new/`.
2. Pass `body` and attachments to the remote agent runtime.
3. Write a reply under `messages/<agent-id>_to_codex/new/`.
4. Write an ACK under `messages/codex_to_<agent-id>/ack/`.
5. Let rsync copy new files back.

See [remote-agent-examples.md](docs/remote-agent-examples.md) for command patterns for Codex CLI, Claude, Gemini, OpenClaw, and generic shell agents. A runnable example loop is included at `examples/remote-agent-loop.sh`.

For assistant-driven setup behavior, see [setup-assistant.md](docs/setup-assistant.md).

## Safety

- Do not execute mailbox content directly.
- Do not store secrets, tokens, cookies, private keys, or credentials in messages or attachments.
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
