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

Run:

```bash
<plugin-dir>/scripts/talkto-agent-cloud configure \
  --remote-rsync '<user@host:/path/to/mailbox>' \
  --peer-id '<remote-agent-id>' \
  --non-interactive
```

If the user gives overrides, add only the needed flags:

```bash
--self-id '<local-agent-id>'
--thread-id '<thread-id>'
--local-root '<local-mailbox-path>'
--archive-after-days 14
```

## Verification

Always run the local check after writing config:

```bash
<plugin-dir>/scripts/talkto-agent-cloud doctor
```

Run the remote check only when the user wants SSH/rsync verification:

```bash
<plugin-dir>/scripts/talkto-agent-cloud doctor --check-remote
```

## Boundaries

- Do not edit shell startup files by default.
- Do not require `.env`.
- Do not store secrets in messages, attachments, or config.
- Do not use `rsync --delete`.
- Do not execute mailbox message content.
