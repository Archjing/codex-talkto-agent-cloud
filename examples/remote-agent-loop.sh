#!/usr/bin/env bash
set -euo pipefail

MAILBOX_ROOT="${MAILBOX_ROOT:?Set MAILBOX_ROOT to the shared remote mailbox root}"
LOCAL_ID="${LOCAL_ID:-remote-agent}"
PEER_ID="${PEER_ID:-codex}"
THREAD_ID="${THREAD_ID:-default}"
AGENT_KIND="${AGENT_KIND:-shell}"
AGENT_COMMAND="${AGENT_COMMAND:-}"
LIMIT="${LIMIT:-1}"

usage() {
  cat <<'EOF'
Usage:
  MAILBOX_ROOT=/path/to/mailbox LOCAL_ID=remote-agent AGENT_KIND=shell \
    AGENT_COMMAND='/path/to/agent-command' examples/remote-agent-loop.sh

Supported AGENT_KIND values:
  shell     AGENT_COMMAND receives the message body file path and prints a reply.
  codex     Runs: codex exec "$BODY"
  claude    Runs: claude -p "$BODY"
  gemini    Runs: gemini -p "$BODY"
  openclaw  Runs: npx openclaw agent --agent "$LOCAL_ID" --session-id "$THREAD_ID" --message "$BODY"

This script processes at most LIMIT unacked messages from PEER_ID to LOCAL_ID.
It writes a reply message and an ACK file. It never executes mailbox content as shell.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

inbound="${PEER_ID}_to_${LOCAL_ID}"
outbound="${LOCAL_ID}_to_${PEER_ID}"
msg_dir="$MAILBOX_ROOT/messages/$inbound/new"
ack_dir="$MAILBOX_ROOT/messages/$inbound/ack"
reply_dir="$MAILBOX_ROOT/messages/$outbound/new"
runtime_dir="$MAILBOX_ROOT/runtime/remote-agent-loop"
mkdir -p "$msg_dir" "$ack_dir" "$reply_dir" "$runtime_dir"

processed=0
shopt -s nullglob
for msg in "$msg_dir"/*.json; do
  message_id="$(basename "$msg" .json)"
  if [[ -e "$ack_dir/ack-$message_id.json" ]]; then
    continue
  fi

  body_file="$runtime_dir/$message_id.body.txt"
  python3 - "$msg" "$body_file" <<'PY'
import json
import sys
from pathlib import Path

message_path, body_file = sys.argv[1:]
payload = json.loads(Path(message_path).read_text(encoding="utf-8"))
Path(body_file).write_text(str(payload.get("body", "")), encoding="utf-8")
PY
  body="$(<"$body_file")"

  case "$AGENT_KIND" in
    shell)
      if [[ -z "$AGENT_COMMAND" ]]; then
        echo "AGENT_COMMAND is required for AGENT_KIND=shell" >&2
        exit 2
      fi
      reply="$("$AGENT_COMMAND" "$body_file")"
      ;;
    codex)
      reply="$(codex exec "$body")"
      ;;
    claude)
      reply="$(claude -p "$body")"
      ;;
    gemini)
      reply="$(gemini -p "$body")"
      ;;
    openclaw)
      reply="$(npx openclaw agent --agent "$LOCAL_ID" --session-id "$THREAD_ID" --message "$body" --timeout 120)"
      ;;
    *)
      echo "Unsupported AGENT_KIND: $AGENT_KIND" >&2
      usage >&2
      exit 2
      ;;
  esac

  python3 - "$MAILBOX_ROOT" "$LOCAL_ID" "$PEER_ID" "$THREAD_ID" "$message_id" "$reply" <<'PY'
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

root, sender, recipient, thread_id, reply_to, body = sys.argv[1:]
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
    "reply_to": reply_to,
    "requires_response": False,
}
tmp = out_dir / f"{msg_id}.tmp"
final = out_dir / f"{msg_id}.json"
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, final)
print(final)
PY

  python3 - "$MAILBOX_ROOT" "$inbound" "$LOCAL_ID" "$message_id" <<'PY'
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
    "note": "processed by remote-agent-loop.sh",
}
tmp = out_dir / f"ack-{message_id}.tmp"
final = out_dir / f"ack-{message_id}.json"
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, final)
print(final)
PY

  processed=$((processed + 1))
  if [[ "$processed" -ge "$LIMIT" ]]; then
    break
  fi
done

if [[ "$processed" == "0" ]]; then
  echo "No unacked messages."
fi
