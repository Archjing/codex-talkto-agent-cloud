#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_MESSAGE = "codex-talkto-agent.mailbox.v1"
SCHEMA_ACK = "codex-talkto-agent.mailbox.ack.v1"
DEFAULT_CONFIG = Path.home() / ".config" / "codex-talkto-agent-cloud" / "config.json"
DEFAULT_REMOTE_CONFIG = Path.home() / ".config" / "codex-talkto-agent-cloud" / "remote-agent.config.json"
DEFAULT_LOCAL_ROOT = Path.home() / ".local" / "share" / "codex-talkto-agent-cloud" / "mailbox"
DEFAULT_BIN_DIR = Path.home() / ".local" / "bin"
CLI_NAME = "talkto-agent-cloud"
PLUGIN_NAME = "codex-talkto-agent-cloud"
AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SUPPORTED_REMOTE_AGENT_KINDS = {"shell", "codex", "claude", "gemini", "openclaw"}


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


def remote_config_path(args: argparse.Namespace) -> Path:
    if getattr(args, "config", None):
        return Path(args.config).expanduser()
    env_path = os.environ.get("CODEX_TALKTO_REMOTE_AGENT_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_REMOTE_CONFIG


def script_path() -> Path:
    return Path(__file__).with_name("talkto-agent-cloud").resolve()


def bin_dir(args: argparse.Namespace) -> Path:
    if getattr(args, "bin_dir", None):
        return Path(args.bin_dir).expanduser()
    return DEFAULT_BIN_DIR


def path_entries() -> list[Path]:
    return [Path(item).expanduser() for item in os.environ.get("PATH", "").split(os.pathsep) if item]


def is_on_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    for entry in path_entries():
        try:
            if entry.resolve() == resolved:
                return True
        except OSError:
            if entry == path:
                return True
    return False


def write_cli_wrapper(target: Path, source: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = f"#!/usr/bin/env sh\nexec {str(source)!r} \"$@\"\n"
    target.write_text(payload, encoding="utf-8")
    target.chmod(0o755)


def install_cli_entry(directory: Path, *, force: bool = False) -> tuple[Path, bool]:
    source = script_path()
    target = directory / CLI_NAME
    if target.exists() or target.is_symlink():
        try:
            if target.resolve() == source:
                return target, False
        except OSError:
            pass
        if not force:
            raise ConfigError(
                f"CLI target already exists: {target}\n"
                "Use --force to replace it, or pass --bin-dir for another directory."
            )
        target.unlink()

    directory.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source)
    except OSError:
        write_cli_wrapper(target, source)
    return target, True


def print_cli_install_result(target: Path, *, created: bool, directory: Path) -> None:
    if created:
        print(f"CLI installed: {target}")
        print(f"Target: {script_path()}")
    else:
        print(f"CLI already installed: {target}")
    if target.is_symlink():
        print("Mode: symlink")
    else:
        print("Mode: wrapper")
    if is_on_path(directory):
        print(f"PATH: ok ({directory})")
    else:
        print(f"PATH: warning ({directory} is not on PATH)")
        print(f"Run with full path for now: {target}")
        print("Add that directory to your shell or launcher PATH if you want the short command everywhere.")


def locate_cli_from_codex_plugin_list() -> Path | None:
    try:
        proc = subprocess.run(
            ["codex", "plugin", "list", "--json"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    for item in payload.get("installed", []):
        if item.get("name") != PLUGIN_NAME:
            continue
        source = item.get("source") or {}
        path = source.get("path")
        if not path:
            continue
        candidate = Path(path).expanduser() / "scripts" / CLI_NAME
        if candidate.is_file():
            return candidate.resolve()
    return None


def collect_config_from_args(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    local_root = prompt_value(
        args,
        "local_root",
        "Local mailbox directory",
        str(DEFAULT_LOCAL_ROOT),
    )
    remote_rsync = prompt_value(
        args,
        "remote_rsync",
        "Remote mailbox rsync root, for example user@host:/home/user/codex-mailbox",
    )
    self_id = prompt_value(args, "self_id", "Local agent ID", "codex")
    peer_id = prompt_value(args, "peer_id", "Remote agent ID")
    thread_id = prompt_value(args, "thread_id", "Default thread ID", "default")

    cfg = build_config_payload(
        local_root=local_root,
        remote_rsync=remote_rsync,
        self_id=self_id,
        peer_id=peer_id,
        thread_id=thread_id,
        archive_after_days=args.archive_after_days,
    )
    validate_config_values(cfg)
    return cfg, Path(cfg["local_root"])


def write_concrete_config(args: argparse.Namespace) -> tuple[dict[str, Any], Path, Path]:
    path = config_path(args)
    if path.exists() and not args.force:
        raise ConfigError(
            f"Config already exists: {path}\n"
            "Use --force to overwrite, or pass --config for another file."
        )

    cfg, root = collect_config_from_args(args)
    ensure_mailbox(root, cfg["self_id"], cfg["peer_id"])
    atomic_json(path, cfg)
    return cfg, root, path


def print_config_result(cfg: dict[str, Any], root: Path, path: Path) -> None:
    print(f"Config written: {path}")
    print(f"Local mailbox: {root}")
    print(f"Remote mailbox: {cfg['remote']['rsync_root']}")
    print(f"Local agent ID: {cfg['self_id']}")
    print(f"Remote agent ID: {cfg['peer_id']}")
    print(f"Thread ID: {cfg['thread_id']}")


def doctor_config(cfg: dict[str, Any], *, check_remote: bool) -> int:
    path = cfg.get("_config_path", "<memory>")
    print(f"Config: {path}")

    found_cli = shutil.which(CLI_NAME)
    if found_cli:
        print(f"CLI: {found_cli}")
    else:
        print(f"CLI: warning ({CLI_NAME} is not on PATH)")
        print(f"CLI install helper: {script_path()} install-cli")

    rsync_path = shutil.which("rsync")
    if not rsync_path:
        print("error: rsync is not installed or not on PATH", file=sys.stderr)
        return 2
    print(f"rsync: {rsync_path}")

    root = Path(cfg["local_root"])
    ensure_mailbox(root, cfg["self_id"], cfg["peer_id"])
    print(f"Local mailbox: {root}")
    print(f"Remote mailbox: {cfg['remote']['rsync_root']}")
    print(f"Direction out: {direction(cfg['self_id'], cfg['peer_id'])}")
    print(f"Direction in: {direction(cfg['peer_id'], cfg['self_id'])}")
    outbound = direction(cfg["self_id"], cfg["peer_id"])
    out_messages = iter_messages(root, outbound)
    out_ack_dir = root / "messages" / outbound / "ack"
    unacked_out = [msg for msg in out_messages if not (out_ack_dir / f"ack-{msg.stem}.json").exists()]
    if unacked_out:
        print(f"Outbound unacked: {len(unacked_out)}")
        print("Remote consumer: warning (remote loop may not be running or may read another mailbox)")
        for msg in unacked_out[-3:]:
            print(f"  pending: {msg.name}")
    else:
        print("Outbound unacked: 0")

    if check_remote:
        print("Remote dry-run sync check: running")
        sync_mailbox(cfg, dry_run=True)
        print("Remote dry-run sync check: ok")
    else:
        print("Remote dry-run sync check: skipped; pass --check-remote to run it")
    return 0


def require_promptable(args: argparse.Namespace, field: str) -> None:
    if getattr(args, "non_interactive", False) or not sys.stdin.isatty():
        raise ConfigError(f"Missing required setup value: {field}")


def prompt_value(args: argparse.Namespace, field: str, prompt: str, default: str | None = None) -> str:
    current = getattr(args, field, None)
    if current:
        return str(current)
    if getattr(args, "non_interactive", False) or not sys.stdin.isatty():
        if default is not None:
            return default
        require_promptable(args, field.replace("_", "-"))
    require_promptable(args, field.replace("_", "-"))
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    if not value and default is not None:
        return default
    if not value:
        raise ConfigError(f"Missing required setup value: {field.replace('_', '-')}")
    return value


def build_config_payload(
    *,
    local_root: str,
    remote_rsync: str,
    self_id: str,
    peer_id: str,
    thread_id: str,
    archive_after_days: int,
) -> dict[str, Any]:
    return {
        "local_root": str(Path(local_root).expanduser()),
        "remote": {
            "rsync_root": remote_rsync.rstrip("/"),
        },
        "self_id": self_id,
        "peer_id": peer_id,
        "thread_id": thread_id,
        "archive_after_days": archive_after_days,
    }


def build_remote_config_payload(
    *,
    mailbox_root: str,
    self_id: str,
    peer_id: str,
    thread_id: str,
    agent_kind: str,
    agent_command: str | None,
    poll_interval_seconds: int,
    archive_after_days: int,
) -> dict[str, Any]:
    agent: dict[str, Any] = {"kind": agent_kind}
    if agent_command:
        agent["command"] = agent_command
    return {
        "mailbox_root": str(Path(mailbox_root).expanduser()),
        "self_id": self_id,
        "peer_id": peer_id,
        "thread_id": thread_id,
        "poll_interval_seconds": poll_interval_seconds,
        "archive_after_days": archive_after_days,
        "agent": agent,
    }


def validate_config_values(cfg: dict[str, Any]) -> None:
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

    for field in ["self_id", "peer_id"]:
        value = str(cfg[field])
        if not AGENT_ID_PATTERN.fullmatch(value):
            raise ConfigError(
                f"{field} must contain only letters, numbers, '.', '_' or '-': {value}"
            )
    if cfg["self_id"] == cfg["peer_id"]:
        raise ConfigError("self_id and peer_id must differ")

    archive_after_days = int(cfg.get("archive_after_days", 14))
    if archive_after_days < 1:
        raise ConfigError("archive_after_days must be >= 1")


def validate_remote_config_values(cfg: dict[str, Any]) -> None:
    required = ["mailbox_root", "self_id", "peer_id", "thread_id"]
    missing = [key for key in required if not cfg.get(key)]
    agent = cfg.get("agent")
    if not isinstance(agent, dict):
        missing.append("agent")
    elif not agent.get("kind"):
        missing.append("agent.kind")
    if missing:
        raise ConfigError(f"Missing remote config fields: {', '.join(missing)}")

    for field in ["self_id", "peer_id"]:
        value = str(cfg[field])
        if not AGENT_ID_PATTERN.fullmatch(value):
            raise ConfigError(
                f"{field} must contain only letters, numbers, '.', '_' or '-': {value}"
            )
    if cfg["self_id"] == cfg["peer_id"]:
        raise ConfigError("self_id and peer_id must differ")

    kind = str(cfg["agent"]["kind"])
    if kind not in SUPPORTED_REMOTE_AGENT_KINDS:
        raise ConfigError(
            f"agent.kind must be one of {', '.join(sorted(SUPPORTED_REMOTE_AGENT_KINDS))}: {kind}"
        )
    if kind == "shell" and not cfg["agent"].get("command"):
        raise ConfigError("agent.command is required when agent.kind is shell")

    poll_interval_seconds = int(cfg.get("poll_interval_seconds", 10))
    if poll_interval_seconds < 1:
        raise ConfigError("poll_interval_seconds must be >= 1")
    archive_after_days = int(cfg.get("archive_after_days", 14))
    if archive_after_days < 1:
        raise ConfigError("archive_after_days must be >= 1")


def load_config(args: argparse.Namespace) -> dict[str, Any]:
    path = config_path(args)
    if not path.exists():
        raise ConfigError(
            f"Config not found: {path}\n"
            "Create one with: talkto-agent-cloud setup --remote-rsync USER@HOST:/path/to/mailbox --peer-id REMOTE_AGENT_ID"
        )
    with path.open(encoding="utf-8") as f:
        cfg = json.load(f)

    cfg = expand_config_env(cfg)
    validate_config_values(cfg)

    cfg["_config_path"] = str(path)
    cfg["local_root"] = str(Path(cfg["local_root"]).expanduser())
    cfg["archive_after_days"] = int(cfg.get("archive_after_days", 14))
    return cfg


def load_remote_config(args: argparse.Namespace) -> dict[str, Any]:
    path = remote_config_path(args)
    if not path.exists():
        raise ConfigError(
            f"Remote agent config not found: {path}\n"
            "Create one with: talkto-agent-cloud remote-init-config --mailbox-root /path/to/mailbox --self-id REMOTE_AGENT_ID --peer-id codex"
        )
    with path.open(encoding="utf-8") as f:
        cfg = json.load(f)

    cfg = expand_config_env(cfg)
    validate_remote_config_values(cfg)
    cfg["_config_path"] = str(path)
    cfg["mailbox_root"] = str(Path(cfg["mailbox_root"]).expanduser())
    cfg["poll_interval_seconds"] = int(cfg.get("poll_interval_seconds", 10))
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


def remote_runtime_dir(root: Path) -> Path:
    path = root / "runtime" / "remote-agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_remote_agent(kind: str, body: str, body_file: Path, cfg: dict[str, Any]) -> str:
    agent = cfg.get("agent") or {}
    if kind == "shell":
        command = str(agent.get("command", ""))
        if not command:
            raise ConfigError("agent.command is required for shell agent")
        command_args = shlex.split(command)
        if not command_args:
            raise ConfigError("agent.command is empty")
        proc = subprocess.run(
            [*command_args, str(body_file)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return proc.stdout.rstrip("\n")
    if kind == "codex":
        proc = subprocess.run(
            ["codex", "exec", body],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        return proc.stdout.rstrip("\n")
    if kind == "claude":
        proc = subprocess.run(
            ["claude", "-p", body],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        return proc.stdout.rstrip("\n")
    if kind == "gemini":
        proc = subprocess.run(
            ["gemini", "-p", body],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        return proc.stdout.rstrip("\n")
    if kind == "openclaw":
        proc = subprocess.run(
            [
                "npx",
                "openclaw",
                "agent",
                "--agent",
                str(cfg["self_id"]),
                "--session-id",
                str(cfg["thread_id"]),
                "--message",
                body,
                "--timeout",
                "120",
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        return proc.stdout.rstrip("\n")
    raise ConfigError(f"Unsupported remote agent kind: {kind}")


def process_remote_messages(cfg: dict[str, Any], *, limit: int | None = None) -> int:
    root = Path(cfg["mailbox_root"])
    self_id = str(cfg["self_id"])
    peer_id = str(cfg["peer_id"])
    ensure_mailbox(root, self_id, peer_id)

    inbound = direction(peer_id, self_id)
    ack_dir = root / "messages" / inbound / "ack"
    count = 0
    for msg_path in iter_messages(root, inbound):
        message_id = msg_path.stem
        if (ack_dir / f"ack-{message_id}.json").exists():
            continue
        payload = read_json(msg_path)
        body = str(payload.get("body", ""))
        body_file = remote_runtime_dir(root) / f"{message_id}.body.txt"
        body_file.write_text(body, encoding="utf-8")
        kind = str(cfg["agent"]["kind"])
        reply = run_remote_agent(kind, body, body_file, cfg)
        write_message(
            root,
            sender=self_id,
            recipient=peer_id,
            thread_id=str(payload.get("thread_id") or cfg["thread_id"]),
            typ="agent_response",
            body=reply,
            attach=[],
            reply_to=message_id,
            requires_response=False,
        )
        write_ack(
            root,
            inbound,
            message_id,
            ack_by=self_id,
            status="processed",
            note=f"processed by remote agent kind={kind}",
        )
        count += 1
        if limit is not None and count >= limit:
            break
    return count


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


def cmd_configure(args: argparse.Namespace) -> int:
    cfg, root, path = write_concrete_config(args)
    print_config_result(cfg, root, path)

    if args.check_remote:
        print("Running remote dry-run sync check...")
        sync_mailbox({**cfg, "_config_path": str(path)}, dry_run=True)
        print("Remote dry-run sync check completed.")
    else:
        print("Next check: run doctor, or doctor --check-remote to test SSH/rsync access.")
    return 0


def cmd_install_cli(args: argparse.Namespace) -> int:
    directory = bin_dir(args)
    target, created = install_cli_entry(directory, force=args.force)
    print_cli_install_result(target, created=created, directory=directory)
    return 0


def cmd_locate_cli(args: argparse.Namespace) -> int:
    current = script_path()
    if current.is_file():
        print(current)
        return 0
    if args.codex_list:
        located = locate_cli_from_codex_plugin_list()
        if located:
            print(located)
            return 0
    print("error: could not locate talkto-agent-cloud CLI", file=sys.stderr)
    return 2


def cmd_uninstall_cli(args: argparse.Namespace) -> int:
    target = bin_dir(args) / CLI_NAME
    if not target.exists() and not target.is_symlink():
        print(f"CLI is not installed at: {target}")
        return 0
    try:
        linked_to_self = target.resolve() == script_path()
    except OSError:
        linked_to_self = False
    if not linked_to_self and not args.force:
        print(f"Refusing to remove CLI target not owned by this plugin: {target}", file=sys.stderr)
        print("Use --force to remove it anyway.", file=sys.stderr)
        return 2
    target.unlink()
    print(f"CLI removed: {target}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config(args)
    return doctor_config(cfg, check_remote=args.check_remote)


def cmd_setup(args: argparse.Namespace) -> int:
    path = config_path(args)
    if path.exists() and not args.force:
        raise ConfigError(
            f"Config already exists: {path}\n"
            "Use --force to overwrite, or pass --config for another file."
        )

    directory = bin_dir(args)
    target, created = install_cli_entry(directory, force=args.force_cli)
    print_cli_install_result(target, created=created, directory=directory)

    cfg, root, path = write_concrete_config(args)
    cfg["_config_path"] = str(path)
    cfg["local_root"] = str(root)
    cfg["archive_after_days"] = int(cfg.get("archive_after_days", 14))
    print_config_result(cfg, root, path)

    print("Running local doctor...")
    doctor_rc = doctor_config(cfg, check_remote=args.check_remote)
    if doctor_rc != 0:
        return doctor_rc
    print("Setup complete.")
    return 0


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


def cmd_remote_init_config(args: argparse.Namespace) -> int:
    path = Path(args.output).expanduser() if args.output else remote_config_path(args)
    if path.exists() and not args.force:
        print(f"Remote agent config already exists: {path}", file=sys.stderr)
        print("Use --force to overwrite.", file=sys.stderr)
        return 2
    cfg = build_remote_config_payload(
        mailbox_root=args.mailbox_root,
        self_id=args.self_id,
        peer_id=args.peer_id,
        thread_id=args.thread_id,
        agent_kind=args.agent_kind,
        agent_command=args.agent_command,
        poll_interval_seconds=args.poll_interval_seconds,
        archive_after_days=args.archive_after_days,
    )
    validate_remote_config_values(cfg)
    ensure_mailbox(Path(cfg["mailbox_root"]), cfg["self_id"], cfg["peer_id"])
    atomic_json(path, cfg)
    print(f"Remote agent config written: {path}")
    print(f"Mailbox root: {cfg['mailbox_root']}")
    print(f"Remote agent ID: {cfg['self_id']}")
    print(f"Peer ID: {cfg['peer_id']}")
    print(f"Agent kind: {cfg['agent']['kind']}")
    return 0


def cmd_remote_run(args: argparse.Namespace) -> int:
    cfg = load_remote_config(args)
    if args.once:
        processed = process_remote_messages(cfg, limit=args.limit)
        print(f"Processed {processed} message(s).")
        return 0

    print(f"Remote agent loop started. Config: {cfg['_config_path']}")
    print("Press Ctrl-C to stop.")
    while True:
        processed = process_remote_messages(cfg, limit=args.limit)
        if processed:
            print(f"Processed {processed} message(s).")
        time.sleep(cfg["poll_interval_seconds"])


def render_remote_setup_prompt(
    *,
    remote_config: dict[str, Any],
    remote_config_name: str,
    runner_name: str,
) -> str:
    mailbox_root = str(remote_config["mailbox_root"])
    self_id = str(remote_config["self_id"])
    peer_id = str(remote_config["peer_id"])
    kind = str(remote_config["agent"]["kind"])
    agent_command = str(remote_config.get("agent", {}).get("command", ""))
    once_cmd = (
        f"python3 {shlex.quote(runner_name)} --config {shlex.quote(remote_config_name)} "
        "remote-run --once"
    )
    loop_cmd = (
        f"python3 {shlex.quote(runner_name)} --config {shlex.quote(remote_config_name)} "
        "remote-run"
    )
    lines = [
        "请配置 codex-talkto-agent@cloud 的远端消息处理循环。",
        "",
        "本条消息附带两个文件：",
        f"- {remote_config_name}: 远端 runner 配置。",
        f"- {runner_name}: 远端消息处理脚本。",
        "",
        "目标：",
        f"- 读取 mailbox: {mailbox_root}",
        f"- 远端 agent ID: {self_id}",
        f"- 对端 Codex ID: {peer_id}",
        f"- agent runtime: {kind}",
    ]
    if kind == "shell":
        lines.append(f"- shell agent command: {agent_command}")
    lines.extend(
        [
            "",
            "请在远端执行以下动作：",
            "1. 保存附件到同一个目录，例如 ~/codex-talkto-agent-cloud/。",
            f"2. 确认 {remote_config_name} 里的 mailbox_root 指向远端本机真实 mailbox 目录。",
            f"3. 确认远端机器有 Python 3，并且 agent runtime `{kind}` 可执行。",
            "4. 先跑一次单次处理命令：",
            "",
            f"   {once_cmd}",
            "",
            "5. 如果单次处理成功，再选择一种常驻方式：",
            "",
            f"   # 手动常驻",
            f"   {loop_cmd}",
            "",
            "   # 或用 cron 每分钟执行一次 --once",
            f"   * * * * * cd ~/codex-talkto-agent-cloud && {once_cmd} >> remote-agent.log 2>&1",
            "",
            "   # 或用 systemd 管理常驻进程，命令使用上面的 remote-run。",
            "",
            "处理成功后，远端应写入：",
            f"- messages/{self_id}_to_{peer_id}/new/<reply>.json",
            f"- messages/{peer_id}_to_{self_id}/ack/ack-<message-id>.json",
            "",
            "安全边界：不要执行 mailbox 消息里的 shell 代码；只把 body 作为文本交给已配置的 agent runtime。",
        ]
    )
    return "\n".join(lines)


def cmd_send_remote_setup(args: argparse.Namespace) -> int:
    cfg = load_config(args)
    root = Path(cfg["local_root"])
    ensure_mailbox(root, cfg["self_id"], cfg["peer_id"])

    remote_mailbox_root = args.remote_mailbox_root or cfg["remote"]["rsync_root"].rsplit(":", 1)[-1]
    remote_cfg = build_remote_config_payload(
        mailbox_root=remote_mailbox_root,
        self_id=args.remote_self_id or cfg["peer_id"],
        peer_id=args.remote_peer_id or cfg["self_id"],
        thread_id=args.thread_id or cfg["thread_id"],
        agent_kind=args.agent_kind,
        agent_command=args.agent_command,
        poll_interval_seconds=args.poll_interval_seconds,
        archive_after_days=args.archive_after_days,
    )
    validate_remote_config_values(remote_cfg)

    bundle_dir = Path(args.bundle_dir).expanduser() if args.bundle_dir else root / "remote_setup"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    remote_config_name = "remote-agent.config.json"
    runner_name = "talkto_agent_cloud.py"
    remote_config_path_out = bundle_dir / remote_config_name
    runner_path_out = bundle_dir / runner_name
    atomic_json(remote_config_path_out, remote_cfg)
    shutil.copy2(Path(__file__), runner_path_out)
    prompt = render_remote_setup_prompt(
        remote_config=remote_cfg,
        remote_config_name=remote_config_name,
        runner_name=runner_name,
    )
    prompt_path = bundle_dir / "remote-setup-prompt.md"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    final = write_message(
        root,
        sender=cfg["self_id"],
        recipient=cfg["peer_id"],
        thread_id=args.thread_id or cfg["thread_id"],
        typ="remote_setup",
        body=prompt,
        attach=[str(remote_config_path_out), str(runner_path_out)],
        reply_to=None,
        requires_response=True,
        message_id=args.message_id,
    )
    print(f"Remote setup bundle: {bundle_dir}")
    print(f"Remote setup prompt: {prompt_path}")
    print(f"Message written: {final}")
    if args.sync:
        sync_mailbox(cfg)
        print("Remote setup message synced.")
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

    setup = sub.add_parser("setup", help="install CLI entrypoint, write config, and run doctor")
    setup.add_argument("--remote-rsync", help="remote mailbox root, e.g. user@host:/path/to/mailbox")
    setup.add_argument("--local-root", help="local mailbox directory")
    setup.add_argument("--self-id", help="local agent ID; default: codex")
    setup.add_argument("--peer-id", help="remote agent ID")
    setup.add_argument("--thread-id", help="default thread ID; default: default")
    setup.add_argument("--archive-after-days", type=int, default=14)
    setup.add_argument("--bin-dir", help="directory for the entrypoint; default: ~/.local/bin")
    setup.add_argument("--force", action="store_true", help="overwrite an existing config")
    setup.add_argument("--force-cli", action="store_true", help="replace an existing CLI entrypoint")
    setup.add_argument("--check-remote", action="store_true", help="run a remote rsync dry-run")
    setup.add_argument("--non-interactive", action="store_true", help="fail instead of prompting for missing values")
    setup.set_defaults(func=cmd_setup)

    configure = sub.add_parser("configure", help="write a ready-to-use concrete config")
    configure.add_argument("--remote-rsync", help="remote mailbox root, e.g. user@host:/path/to/mailbox")
    configure.add_argument("--local-root", help="local mailbox directory")
    configure.add_argument("--self-id", help="local agent ID; default: codex")
    configure.add_argument("--peer-id", help="remote agent ID")
    configure.add_argument("--thread-id", help="default thread ID; default: default")
    configure.add_argument("--archive-after-days", type=int, default=14)
    configure.add_argument("--force", action="store_true")
    configure.add_argument("--check-remote", action="store_true", help="run sync --dry-run after writing config")
    configure.add_argument("--non-interactive", action="store_true", help="fail instead of prompting for missing values")
    configure.set_defaults(func=cmd_configure)

    install_cli = sub.add_parser("install-cli", help="install a user-level CLI entrypoint")
    install_cli.add_argument("--bin-dir", help="directory for the entrypoint; default: ~/.local/bin")
    install_cli.add_argument("--force", action="store_true")
    install_cli.set_defaults(func=cmd_install_cli)

    locate_cli = sub.add_parser("locate-cli", help="print this plugin's CLI path")
    locate_cli.add_argument("--codex-list", action="store_true", help="also try codex plugin list --json")
    locate_cli.set_defaults(func=cmd_locate_cli)

    uninstall_cli = sub.add_parser("uninstall-cli", help="remove the user-level CLI entrypoint")
    uninstall_cli.add_argument("--bin-dir", help="directory containing the entrypoint; default: ~/.local/bin")
    uninstall_cli.add_argument("--force", action="store_true")
    uninstall_cli.set_defaults(func=cmd_uninstall_cli)

    doctor = sub.add_parser("doctor", help="validate config and optional remote rsync access")
    doctor.add_argument("--check-remote", action="store_true", help="run a remote rsync dry-run")
    doctor.set_defaults(func=cmd_doctor)

    init = sub.add_parser("init-config", help="write a user-editable config template")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init_config)

    remote_init = sub.add_parser("remote-init-config", help="write a remote-side agent runner config")
    remote_init.add_argument("--output", help="remote config path; default: CODEX_TALKTO_REMOTE_AGENT_CONFIG or ~/.config/codex-talkto-agent-cloud/remote-agent.config.json")
    remote_init.add_argument("--mailbox-root", required=True, help="remote machine mailbox root path")
    remote_init.add_argument("--self-id", required=True, help="remote agent ID")
    remote_init.add_argument("--peer-id", required=True, help="peer/local Codex ID")
    remote_init.add_argument("--thread-id", default="default")
    remote_init.add_argument("--agent-kind", choices=sorted(SUPPORTED_REMOTE_AGENT_KINDS), default="shell")
    remote_init.add_argument("--agent-command", help="command for agent-kind=shell; receives a body-file path")
    remote_init.add_argument("--poll-interval-seconds", type=int, default=10)
    remote_init.add_argument("--archive-after-days", type=int, default=14)
    remote_init.add_argument("--force", action="store_true")
    remote_init.add_argument("--non-interactive", action="store_true", help="reserved for assistant-driven setup scripts")
    remote_init.set_defaults(func=cmd_remote_init_config)

    remote_run = sub.add_parser("remote-run", help="run the remote-side mailbox consumer")
    remote_run.add_argument("--once", action="store_true", help="process available messages once and exit")
    remote_run.add_argument("--limit", type=int, default=None, help="maximum messages per pass")
    remote_run.set_defaults(func=cmd_remote_run)

    remote_setup = sub.add_parser("send-remote-setup", help="send a remote setup prompt with config and runner attachments")
    remote_setup.add_argument("--remote-mailbox-root", help="remote machine mailbox root path; default: path part of remote.rsync_root")
    remote_setup.add_argument("--remote-self-id", help="remote agent ID; default: local peer_id")
    remote_setup.add_argument("--remote-peer-id", help="remote peer ID; default: local self_id")
    remote_setup.add_argument("--thread-id")
    remote_setup.add_argument("--agent-kind", choices=sorted(SUPPORTED_REMOTE_AGENT_KINDS), default="shell")
    remote_setup.add_argument("--agent-command", help="command for agent-kind=shell; receives a body-file path")
    remote_setup.add_argument("--poll-interval-seconds", type=int, default=10)
    remote_setup.add_argument("--archive-after-days", type=int, default=14)
    remote_setup.add_argument("--bundle-dir", help="local directory for generated remote setup attachments")
    remote_setup.add_argument("--message-id")
    remote_setup.add_argument("--sync", action="store_true", help="sync mailbox after writing the setup message")
    remote_setup.set_defaults(func=cmd_send_remote_setup)

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
