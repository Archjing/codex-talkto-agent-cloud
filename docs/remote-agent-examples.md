# Remote Agent Examples

These examples show how a remote machine can participate in the mailbox protocol. The remote runtime can be any common agent CLI or service. OpenClaw is only one option.

Assume:

```bash
MAILBOX_ROOT=/home/user/codex-mailbox
LOCAL_ID=remote-agent
PEER_ID=codex
THREAD_ID=default
```

## Runnable Loop

Recommended first-run flow:

1. Local Codex runs `talkto-agent-cloud send-remote-setup --agent-kind codex --sync`.
2. The user gives that `remote_setup` message to the remote agent.
3. The remote agent saves both attachments in one directory:
   - `remote-agent.config.json`
   - `talkto_agent_cloud.py`
4. The remote agent runs one of:

```bash
# Process pending messages once.
python3 talkto_agent_cloud.py --config remote-agent.config.json remote-run --once

# Or keep polling.
python3 talkto_agent_cloud.py --config remote-agent.config.json remote-run
```

The same runner can be invoked by cron or systemd. For cron:

```cron
* * * * * cd ~/codex-talkto-agent-cloud && python3 talkto_agent_cloud.py --config remote-agent.config.json remote-run --once >> remote-agent.log 2>&1
```

The plugin also includes a standalone shell example:

```bash
MAILBOX_ROOT=/home/user/codex-mailbox \
LOCAL_ID=remote-agent \
PEER_ID=codex \
AGENT_KIND=codex \
LIMIT=1 \
examples/remote-agent-loop.sh
```

Use `AGENT_KIND=claude`, `AGENT_KIND=gemini`, `AGENT_KIND=openclaw`, or `AGENT_KIND=shell` for other runtimes. For `shell`, set `AGENT_COMMAND` to a command that accepts a body-file path and prints a reply.

## Minimal Reply Writer

This writes a reply from the remote agent to Codex:

```bash
python3 - "$MAILBOX_ROOT" "$LOCAL_ID" "$PEER_ID" "$THREAD_ID" "reply text" <<'PY'
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

root, sender, recipient, thread_id, body = sys.argv[1:]
msg_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + sender + "-" + secrets.token_hex(3)
direction = f"{sender}_to_{recipient}"
out_dir = Path(root) / "messages" / direction / "new"
out_dir.mkdir(parents=True, exist_ok=True)
payload = {
    "schema": "codex-talkto-agent.mailbox.v1",
    "id": msg_id,
    "thread_id": thread_id,
    "from": sender,
    "to": recipient,
    "type": "agent_response",
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "body": body,
    "attachments": [],
    "reply_to": None,
    "requires_response": False,
}
tmp = out_dir / f"{msg_id}.tmp"
final = out_dir / f"{msg_id}.json"
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, final)
print(final)
PY
```

## Minimal ACK Writer

```bash
python3 - "$MAILBOX_ROOT" "codex_to_$LOCAL_ID" "$LOCAL_ID" "$MESSAGE_ID" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

root, direction, ack_by, message_id = sys.argv[1:]
out_dir = Path(root) / "messages" / direction / "ack"
out_dir.mkdir(parents=True, exist_ok=True)
payload = {
    "schema": "codex-talkto-agent.mailbox.ack.v1",
    "message_id": message_id,
    "direction": direction,
    "ack_by": ack_by,
    "status": "processed",
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "note": "processed by remote agent",
}
tmp = out_dir / f"ack-{message_id}.tmp"
final = out_dir / f"ack-{message_id}.json"
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, final)
print(final)
PY
```

## Generic Shell Agent

For a simple remote command that reads a message body file and prints a reply:

```bash
MESSAGE_JSON="$MAILBOX_ROOT/messages/codex_to_$LOCAL_ID/new/<message-id>.json"
BODY_FILE=/tmp/codex-talkto-body.txt
jq -r '.body' "$MESSAGE_JSON" > "$BODY_FILE"

REPLY="$(/path/to/your-agent-command "$BODY_FILE")"
```

Then write `REPLY` back using the minimal reply writer above and ACK the original message.

## Codex CLI

On a remote machine with Codex CLI:

```bash
python3 talkto_agent_cloud.py \
  remote-init-config \
  --output remote-agent.config.json \
  --mailbox-root /home/user/codex-mailbox \
  --self-id remote-agent \
  --peer-id codex \
  --agent-kind codex \
  --non-interactive
python3 talkto_agent_cloud.py --config remote-agent.config.json remote-run --once
```

Manual equivalent:

```bash
MESSAGE_JSON="$MAILBOX_ROOT/messages/codex_to_$LOCAL_ID/new/<message-id>.json"
BODY="$(jq -r '.body' "$MESSAGE_JSON")"
REPLY="$(codex exec "$BODY")"
```

Then write `REPLY` to `messages/$LOCAL_ID_to_codex/new/` and ACK the original message.

## Claude Code

On a remote machine with Claude Code:

```bash
MESSAGE_JSON="$MAILBOX_ROOT/messages/codex_to_$LOCAL_ID/new/<message-id>.json"
BODY="$(jq -r '.body' "$MESSAGE_JSON")"
REPLY="$(claude -p "$BODY")"
```

Then write `REPLY` to `messages/$LOCAL_ID_to_codex/new/` and ACK the original message.

## Gemini CLI

On a remote machine with Gemini CLI:

```bash
MESSAGE_JSON="$MAILBOX_ROOT/messages/codex_to_$LOCAL_ID/new/<message-id>.json"
BODY="$(jq -r '.body' "$MESSAGE_JSON")"
REPLY="$(gemini -p "$BODY")"
```

Then write `REPLY` to `messages/$LOCAL_ID_to_codex/new/` and ACK the original message.

## OpenClaw

OpenClaw can also be used as the remote agent, but it is not required:

```bash
python3 talkto_agent_cloud.py \
  remote-init-config \
  --output remote-agent.config.json \
  --mailbox-root /home/user/codex-mailbox \
  --self-id remote-agent \
  --peer-id codex \
  --agent-kind openclaw \
  --non-interactive
python3 talkto_agent_cloud.py --config remote-agent.config.json remote-run --once
```

Manual equivalent:

```bash
MESSAGE_JSON="$MAILBOX_ROOT/messages/codex_to_$LOCAL_ID/new/<message-id>.json"
BODY="$(jq -r '.body' "$MESSAGE_JSON")"
REPLY="$(npx openclaw agent --agent "$LOCAL_ID" --session-id "$THREAD_ID" --message "$BODY" --timeout 120)"
```

Then write `REPLY` to `messages/$LOCAL_ID_to_codex/new/` and ACK the original message.

## Notes

- Prefer a supervised service, systemd timer, cron job, or explicit manual command on the remote side.
- Keep mailbox processing idempotent: skip messages that already have ACK files.
- Do not run shell snippets from mailbox messages.
- Do not delete mailbox files during sync.
