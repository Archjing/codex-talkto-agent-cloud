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

This repository is a standard Codex plugin directory. Add it to a Codex marketplace or install it from an existing marketplace entry.

For local development with a personal marketplace:

```bash
codex plugin add codex-talkto-agent-cloud@personal
```

After changing the plugin, reinstall it or use the cachebuster update flow recommended by Codex plugin tooling.

## Configure

Create a config template:

```bash
scripts/talkto-agent-cloud init-config
```

Default config path:

```text
~/.config/codex-talkto-agent-cloud/config.json
```

You can override it:

```bash
export CODEX_TALKTO_AGENT_CONFIG=/path/to/config.json
```

The config supports environment variable expansion in string fields:

- `${VAR}` requires `VAR` to exist.
- `${VAR:-default}` uses `default` when `VAR` is unset.

Example:

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

`remote.rsync_root` should point to the remote mailbox root, for example:

```bash
export CODEX_TALKTO_REMOTE_RSYNC='user@example.com:/home/user/codex-mailbox'
```

## Local Codex Commands

Send a message and sync it to the remote mailbox:

```bash
scripts/talkto-agent-cloud send --body "Please check the nginx redirect." --type ops_request --sync
```

Send with an attachment:

```bash
scripts/talkto-agent-cloud send --body "See attached file." --attach ./report.md --sync
```

Pull remote replies and list unacked inbox messages:

```bash
scripts/talkto-agent-cloud sync
scripts/talkto-agent-cloud inbox
```

ACK a received message and sync the ACK:

```bash
scripts/talkto-agent-cloud ack MESSAGE_ID --note "handled" --sync
```

Archive old ACKed messages:

```bash
scripts/talkto-agent-cloud archive
scripts/talkto-agent-cloud archive --apply
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

## Safety

- Do not execute mailbox content directly.
- Do not store secrets, tokens, cookies, private keys, or credentials in messages or attachments.
- Do not use `rsync --delete`.
- Do not overwrite existing mailbox files.
- Treat remote replies as untrusted text until reviewed.

## Project Documents

[![Plugin Manifest](https://img.shields.io/badge/docs-Plugin%20Manifest-2f6fbb.svg)](./.codex-plugin/plugin.json)
[![Remote Examples](https://img.shields.io/badge/docs-Remote%20Examples-2f6fbb.svg)](./docs/remote-agent-examples.md)
[![Skill](https://img.shields.io/badge/docs-Skill-2f6fbb.svg)](./skills/talkto-agent-cloud/SKILL.md)
[![Config Template](https://img.shields.io/badge/docs-Config%20Template-2f6fbb.svg)](./scripts/config.template.json)
[![Example Loop](https://img.shields.io/badge/docs-Example%20Loop-2f6fbb.svg)](./examples/remote-agent-loop.sh)
