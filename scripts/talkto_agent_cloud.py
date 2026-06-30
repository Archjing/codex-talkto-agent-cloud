#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_MESSAGE = "codex-talkto-agent.mailbox.v1"
SCHEMA_ACK = "codex-talkto-agent.mailbox.ack.v1"
DEFAULT_CONFIG = Path.home() / ".config" / "codex-talkto-agent-cloud" / "config.json"


class ConfigError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_id(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{prefix}-{secrets.token_hex(3)}"


def config_path(args: argparse.Namespace) -> Path:
    if getattr(args, "config", None):
        return Path(args.config).expanduser()
    env_path = os.environ.get("CODEX_TALKTO_AGENT_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_CONFIG


def load_config(args: argparse.Namespace) -> dict[str, Any]:
    path = config_path(args)
    if not path.exists():
        raise ConfigError(
            f"Config not found: {path}\n"
            "Create one with: talkto-agent-cloud init-config"
        )
    with path.open(encoding="utf-8") as f:
        cfg = json.load(f)

    cfg = expand_config_env(cfg)

    required = ["local_root", "self_id", "peer_id", "thread_id"]
    missing = [key for key in required if not cfg.get(key)]
    if not isinstance(cfg.get("remote"), dict) or not cfg["remote"].get("rsync_root"):
        missing.append("remote.rsync_root")
    if missing:
        raise ConfigError(f"Missing config fields: {', '.join(missing)}")

    placeholder_values = {
        "/absolute/path/to/local/mailbox",
        "user@host:/absolute/path/to/remote/mailbox",
        "local-agent-id",
        "cloud-agent-id",
        "conversation-or-bridge-id",
    }
    flattened = [
        str(cfg.get("local_root", "")),
        str(cfg["remote"].get("rsync_root", "")),
        str(cfg.get("self_id", "")),
        str(cfg.get("peer_id", "")),
        str(cfg.get("thread_id", "")),
    ]
    unresolved = [value for value in flattened if value in placeholder_values]
    if unresolved:
        raise ConfigError(f"Config still contains template placeholders: {', '.join(unresolved)}")

    cfg["_config_path"] = str(path)
    cfg["local_root"] = str(Path(cfg["local_root"]).expanduser())
    cfg["archive_after_days"] = int(cfg.get("archive_after_days", 14))
    return cfg


def direction(sender: str, recipient: str) -> str:
    return f"{sender}_to_{recipient}"


def ensure_mailbox(root: Path, self_id: str, peer_id: str) -> None:
    for d in [direction(self_id, peer_id), direction(peer_id, self_id)]:
        (root / "messages" / d / "new").mkdir(parents=True, exist_ok=True)
        (root / "messages" / d / "ack").mkdir(parents=True, exist_ok=True)
        (root / "files" / d).mkdir(parents=True, exist_ok=True)
    (root / "archive").mkdir(parents=True, exist_ok=True)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def expand_env_string(value: str) -> str:
    """Expand ${VAR} and ${VAR:-default} without invoking a shell."""
    result: list[str] = []
    i = 0
    while i < len(value):
        if value.startswith("${", i):
            end = value.find("}", i + 2)
            if end == -1:
                result.append(value[i])
                i += 1
                continue
            expr = value[i + 2 : end]
            if ":-" in expr:
                key, default = expr.split(":-", 1)
                result.append(os.environ.get(key, default))
            else:
                if expr not in os.environ:
                    raise ConfigError(f"Environment variable is not set: {expr}")
                result.append(os.environ[expr])
            i = end + 1
        else:
            result.append(value[i])
            i += 1
    return "".join(result)


def expand_config_env(value: Any) -> Any:
    if isinstance(value, str):
        return expand_env_string(value)
    if isinstance(value, list):
        return [expand_config_env(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_config_env(item) for key, item in value.items()}
    return value


def write_ack(
    root: Path,
    direction_name: str,
    message_id: str,
    *,
    ack_by: str,
    status: str = "received",
    note: str = "",
) -> Path:
    payload = {
        "schema": SCHEMA_ACK,
        "message_id": message_id,
        "direction": direction_name,
        "ack_by": ack_by,
        "status": status,
        "created_at": utc_now(),
        "note": note,
    }
    final = root / "messages" / direction_name / "ack" / f"ack-{message_id}.json"
    atomic_json(final, payload)
    return final


def write_message(
    root: Path,
    *,
    sender: str,
    recipient: str,
    thread_id: str,
    typ: str,
    body: str,
    attach: list[str],
    reply_to: str | None,
    requires_response: bool,
    message_id: str | None = None,
) -> Path:
    if sender == recipient:
        raise ConfigError("sender and recipient must differ")

    d = direction(sender, recipient)
    msg_id = message_id or utc_id(sender)
    msg_dir = root / "messages" / d / "new"
    attach_dir = root / "files" / d / msg_id
    attach_dir.mkdir(parents=True, exist_ok=True)

    attachments: list[str] = []
    for item in attach:
        src = Path(item)
        if not src.is_file():
            raise ConfigError(f"Attachment is not a file: {src}")
        dest = attach_dir / src.name
        if dest.exists():
            raise ConfigError(f"Attachment destination already exists: {dest}")
        shutil.copy2(src, dest)
        attachments.append(str(Path("files") / d / msg_id / src.name))

    payload = {
        "schema": SCHEMA_MESSAGE,
        "id": msg_id,
        "thread_id": thread_id,
        "from": sender,
        "to": recipient,
        "type": typ,
        "created_at": utc_now(),
        "body": body,
        "attachments": attachments,
        "reply_to": reply_to,
        "requires_response": requires_response,
    }
    final = msg_dir / f"{msg_id}.json"
    if final.exists():
        raise ConfigError(f"Message already exists: {final}")
    atomic_json(final, payload)
    return final


def rsync(src: str, dst: str, dry_run: bool, extra_args: list[str] | None = None) -> None:
    cmd = ["rsync", "-az", "--ignore-existing"]
    if extra_args:
        cmd.extend(extra_args)
    if dry_run:
        cmd.extend(["--dry-run", "--itemize-changes"])
    cmd.extend([src, dst])
    subprocess.run(cmd, check=True)


def sync_mailbox(cfg: dict[str, Any], *, dry_run: bool = False) -> None:
    root = Path(cfg["local_root"])
    remote = cfg["remote"]["rsync_root"].rstrip("/")
    self_id = cfg["self_id"]
    peer_id = cfg["peer_id"]
    ensure_mailbox(root, self_id, peer_id)

    peer_to_self = direction(peer_id, self_id)
    self_to_peer = direction(self_id, peer_id)

    # Seed the remote directory skeleton before pulls. A fresh remote mailbox
    # commonly lacks peer_to_self/new, which would otherwise make rsync fail.
    rsync(
        f"{root}/",
        f"{remote}/",
        dry_run,
        extra_args=["--include", "*/", "--exclude", "*"],
    )

    def pull(remote_subpath: str, local_subpath: str) -> None:
        rsync(f"{remote}/{remote_subpath}/", f"{root / local_subpath}/", dry_run)

    def push(local_subpath: str, remote_subpath: str) -> None:
        rsync(f"{root / local_subpath}/", f"{remote}/{remote_subpath}/", dry_run)

    pull(f"messages/{peer_to_self}/new", f"messages/{peer_to_self}/new")
    pull(f"files/{peer_to_self}", f"files/{peer_to_self}")
    push(f"messages/{self_to_peer}/new", f"messages/{self_to_peer}/new")
    push(f"files/{self_to_peer}", f"files/{self_to_peer}")

    for d in [peer_to_self, self_to_peer]:
        pull(f"messages/{d}/ack", f"messages/{d}/ack")
        push(f"messages/{d}/ack", f"messages/{d}/ack")


def cmd_init_config(args: argparse.Namespace) -> int:
    path = config_path(args)
    if path.exists() and not args.force:
        print(f"Config already exists: {path}", file=sys.stderr)
        print("Use --force to overwrite.", file=sys.stderr)
        return 2
    template = Path(__file__).with_name("config.template.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, path)
    print(path)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    cfg = load_config(args)
    sync_mailbox(cfg, dry_run=bool(args.dry_run))
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    cfg = load_config(args)
    root = Path(cfg["local_root"])
    sender = args.sender or cfg["self_id"]
    recipient = args.recipient or cfg["peer_id"]
    ensure_mailbox(root, cfg["self_id"], cfg["peer_id"])

    body = args.body or ""
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")

    final = write_message(
        root,
        sender=sender,
        recipient=recipient,
        thread_id=args.thread_id or cfg["thread_id"],
        typ=args.type,
        body=body,
        attach=args.attach,
        reply_to=args.reply_to,
        requires_response=args.requires_response,
        message_id=args.message_id,
    )
    print(final)
    if args.sync:
        sync_mailbox(cfg)
    return 0


def iter_messages(root: Path, d: str) -> list[Path]:
    msg_dir = root / "messages" / d / "new"
    if not msg_dir.exists():
        return []
    return sorted(msg_dir.glob("*.json"))


def cmd_inbox(args: argparse.Namespace) -> int:
    cfg = load_config(args)
    root = Path(cfg["local_root"])
    d = args.direction or direction(cfg["peer_id"], cfg["self_id"])
    ack_dir = root / "messages" / d / "ack"
    messages = iter_messages(root, d)
    count = 0
    for msg_path in messages:
        ack_path = ack_dir / f"ack-{msg_path.stem}.json"
        if not args.all and ack_path.exists():
            continue
        count += 1
        if args.paths:
            print(msg_path)
            continue
        with msg_path.open(encoding="utf-8") as f:
            msg = json.load(f)
        print(f"id: {msg.get('id')}")
        print(f"from: {msg.get('from')} -> {msg.get('to')}")
        print(f"created_at: {msg.get('created_at')}")
        print(f"requires_response: {msg.get('requires_response')}")
        print(f"ack: {'yes' if ack_path.exists() else 'no'}")
        print("body:")
        print(msg.get("body", ""))
        attachments = msg.get("attachments") or []
        if attachments:
            print("attachments:")
            for item in attachments:
                print(f"- {item}")
        print("---")
    if count == 0 and not args.paths:
        print("No messages.")
    return 0


def cmd_ack(args: argparse.Namespace) -> int:
    cfg = load_config(args)
    root = Path(cfg["local_root"])
    d = args.direction or direction(cfg["peer_id"], cfg["self_id"])
    target = Path(args.message)
    if target.is_file():
        message_id = read_json(target)["id"]
    else:
        message_id = args.message
    final = write_ack(root, d, message_id, ack_by=args.by or cfg["self_id"], status=args.status, note=args.note)
    print(final)
    if args.sync:
        sync_mailbox(cfg)
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    cfg = load_config(args)
    root = Path(cfg["local_root"])
    days = args.days if args.days is not None else cfg["archive_after_days"]
    cutoff_seconds = days * 86400
    now = datetime.now(timezone.utc).timestamp()
    directions = [direction(cfg["peer_id"], cfg["self_id"]), direction(cfg["self_id"], cfg["peer_id"])]

    for d in directions:
        ack_dir = root / "messages" / d / "ack"
        if not ack_dir.exists():
            continue
        for ack in sorted(ack_dir.glob("ack-*.json")):
            age = now - ack.stat().st_mtime
            if age <= cutoff_seconds:
                continue
            message_id = ack.name.removeprefix("ack-").removesuffix(".json")
            msg = root / "messages" / d / "new" / f"{message_id}.json"
            if not msg.exists():
                continue
            yyyy_mm = datetime.fromtimestamp(ack.stat().st_mtime, timezone.utc).strftime("%Y-%m")
            dest = root / "archive" / yyyy_mm / d
            if not args.apply:
                print(f"Would archive {d}/{message_id} -> {dest}")
                continue
            for sub in ["messages", "ack", "files"]:
                (dest / sub).mkdir(parents=True, exist_ok=True)
            shutil.move(str(msg), str(dest / "messages" / msg.name))
            shutil.move(str(ack), str(dest / "ack" / ack.name))
            files_dir = root / "files" / d / message_id
            if files_dir.exists():
                shutil.move(str(files_dir), str(dest / "files" / files_dir.name))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="talkto-agent-cloud")
    parser.add_argument("--config", help="config file path; overrides CODEX_TALKTO_AGENT_CONFIG")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-config", help="write a user-editable config template")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init_config)

    sync = sub.add_parser("sync", help="bidirectional rsync without delete or overwrite")
    sync.add_argument("--dry-run", action="store_true")
    sync.set_defaults(func=cmd_sync)

    send = sub.add_parser("send", help="send a message")
    send.add_argument("--body", default="")
    send.add_argument("--body-file")
    send.add_argument("--attach", action="append", default=[])
    send.add_argument("--from", dest="sender")
    send.add_argument("--to", dest="recipient")
    send.add_argument("--thread-id")
    send.add_argument("--type", default="message")
    send.add_argument("--reply-to")
    send.add_argument("--message-id")
    send.add_argument("--requires-response", action=argparse.BooleanOptionalAction, default=True)
    send.add_argument("--sync", action="store_true", help="sync mailbox after writing the message")
    send.set_defaults(func=cmd_send)

    inbox = sub.add_parser("inbox", help="list messages")
    inbox.add_argument("--direction")
    inbox.add_argument("--all", action="store_true")
    inbox.add_argument("--paths", action="store_true")
    inbox.set_defaults(func=cmd_inbox)

    ack = sub.add_parser("ack", help="write an ACK")
    ack.add_argument("message")
    ack.add_argument("--direction")
    ack.add_argument("--by")
    ack.add_argument("--status", default="received")
    ack.add_argument("--note", default="")
    ack.add_argument("--sync", action="store_true", help="sync mailbox after writing the ACK")
    ack.set_defaults(func=cmd_ack)

    archive = sub.add_parser("archive", help="archive old ACKed messages")
    archive.add_argument("--days", type=int)
    archive.add_argument("--apply", action="store_true")
    archive.set_defaults(func=cmd_archive)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"error: command failed with exit code {exc.returncode}: {' '.join(exc.cmd)}", file=sys.stderr)
        return exc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
