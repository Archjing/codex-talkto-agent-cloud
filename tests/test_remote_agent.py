from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "talkto_agent_cloud.py"


class RemoteAgentTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_remote_init_config_writes_remote_runner_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "remote.config.json"
            mailbox_root = tmp_path / "mailbox"

            self.run_cli(
                "remote-init-config",
                "--output",
                str(config_path),
                "--mailbox-root",
                str(mailbox_root),
                "--self-id",
                "luke",
                "--peer-id",
                "codex",
                "--agent-kind",
                "codex",
                "--non-interactive",
            )

            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(cfg["mailbox_root"], str(mailbox_root))
            self.assertEqual(cfg["self_id"], "luke")
            self.assertEqual(cfg["peer_id"], "codex")
            self.assertEqual(cfg["agent"]["kind"], "codex")
            self.assertEqual(cfg["poll_interval_seconds"], 10)

    def test_remote_run_processes_unacked_message_and_writes_reply_and_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mailbox_root = tmp_path / "mailbox"
            config_path = tmp_path / "remote.config.json"
            agent = tmp_path / "agent.sh"
            agent.write_text(
                "#!/usr/bin/env sh\nlast=''\nfor arg in \"$@\"; do last=\"$arg\"; done\nprintf 'remote reply: '\ncat \"$last\"\n",
                encoding="utf-8",
            )
            agent.chmod(0o755)

            self.run_cli(
                "remote-init-config",
                "--output",
                str(config_path),
                "--mailbox-root",
                str(mailbox_root),
                "--self-id",
                "luke",
                "--peer-id",
                "codex",
                "--agent-kind",
                "shell",
                "--agent-command",
                f"{agent} --ignored-flag",
                "--non-interactive",
            )

            message_dir = mailbox_root / "messages" / "codex_to_luke" / "new"
            message_dir.mkdir(parents=True, exist_ok=True)
            message_id = "msg-001"
            message = {
                "schema": "codex-talkto-agent.mailbox.v1",
                "id": message_id,
                "thread_id": "default",
                "from": "codex",
                "to": "luke",
                "type": "message",
                "created_at": "2026-06-30T00:00:00+00:00",
                "body": "hello",
                "attachments": [],
                "reply_to": None,
                "requires_response": True,
            }
            (message_dir / f"{message_id}.json").write_text(
                json.dumps(message, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            result = self.run_cli("--config", str(config_path), "remote-run", "--once")
            self.assertIn("Processed 1 message(s).", result.stdout)

            ack = mailbox_root / "messages" / "codex_to_luke" / "ack" / f"ack-{message_id}.json"
            self.assertTrue(ack.exists())
            ack_payload = json.loads(ack.read_text(encoding="utf-8"))
            self.assertEqual(ack_payload["message_id"], message_id)
            self.assertEqual(ack_payload["ack_by"], "luke")
            self.assertEqual(ack_payload["status"], "processed")

            replies = sorted((mailbox_root / "messages" / "luke_to_codex" / "new").glob("*.json"))
            self.assertEqual(len(replies), 1)
            reply = json.loads(replies[0].read_text(encoding="utf-8"))
            self.assertEqual(reply["from"], "luke")
            self.assertEqual(reply["to"], "codex")
            self.assertEqual(reply["reply_to"], message_id)
            self.assertEqual(reply["body"], "remote reply: hello")

            second = self.run_cli("--config", str(config_path), "remote-run", "--once")
            self.assertIn("Processed 0 message(s).", second.stdout)
            self.assertEqual(len(list((mailbox_root / "messages" / "luke_to_codex" / "new").glob("*.json"))), 1)

    def test_send_remote_setup_attaches_remote_config_and_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "local.config.json"
            local_root = tmp_path / "local-mailbox"
            cfg = {
                "local_root": str(local_root),
                "remote": {"rsync_root": "user@example.com:/srv/codex-mailbox"},
                "self_id": "codex",
                "peer_id": "luke",
                "thread_id": "default",
                "archive_after_days": 14,
            }
            config_path.write_text(json.dumps(cfg, ensure_ascii=False) + "\n", encoding="utf-8")

            self.run_cli(
                "--config",
                str(config_path),
                "send-remote-setup",
                "--agent-kind",
                "codex",
                "--message-id",
                "remote-setup-001",
            )

            message_path = local_root / "messages" / "codex_to_luke" / "new" / "remote-setup-001.json"
            self.assertTrue(message_path.exists())
            message = json.loads(message_path.read_text(encoding="utf-8"))
            self.assertEqual(message["type"], "remote_setup")
            self.assertIn("remote-run --once", message["body"])
            self.assertIn("cron", message["body"])
            self.assertIn("systemd", message["body"])

            attachments = message["attachments"]
            self.assertEqual(len(attachments), 2)
            attached_files = [local_root / item for item in attachments]
            self.assertTrue(any(path.name == "remote-agent.config.json" for path in attached_files))
            self.assertTrue(any(path.name == "talkto_agent_cloud.py" for path in attached_files))

            remote_config = next(path for path in attached_files if path.name == "remote-agent.config.json")
            remote_payload = json.loads(remote_config.read_text(encoding="utf-8"))
            self.assertEqual(remote_payload["mailbox_root"], "/srv/codex-mailbox")
            self.assertEqual(remote_payload["self_id"], "luke")
            self.assertEqual(remote_payload["peer_id"], "codex")
            self.assertEqual(remote_payload["agent"]["kind"], "codex")


if __name__ == "__main__":
    unittest.main()
