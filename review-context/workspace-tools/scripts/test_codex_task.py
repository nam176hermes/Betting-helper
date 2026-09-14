"""Run: python3 -m unittest discover -s scripts -p 'test_codex_task.py'."""

import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import benchmark_codex as benchmark
import codex_task as task
from analyze_codex_context import analyze


class WorkflowCheck(unittest.TestCase):
    def test_operational_guards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "sample.txt").write_text("first\nsecond\n")
            packet: dict[str, Any] = {
                "task": "Check a sample",
                "expected_output": "Evidence",
                "cwd": str(root),
                "target_head": "UNBORN",
                "dirty_ownership": {"sample.txt": "user"},
                "files": ["sample.txt"],
                "constraints": [],
                "known_verified_facts": [],
                "authority": "NONE",
                "required_checks": [
                    {
                        "id": "check",
                        "argv": [sys.executable, "-c", 'print("ok")'],
                        "tier": "V0",
                    }
                ],
                "do_not_reread": [],
                "exit_condition": "checked",
                "role": "implementation",
                "risk": {**dict.fromkeys(task.AXES, 0), "critical_flags": []},
                "areas": ["docs"],
            }
            source = root.parent / (root.name + "-packet.json")
            state = root.parent / (root.name + "-state.json")
            try:
                task.save(source, packet)
                task.prepare(source, state)
                self.assertEqual(task.route(packet)["model"], "gpt-5.6-luna")
                coordinator = copy.deepcopy(packet)
                coordinator["role"] = "coordinator"
                for area, ambiguity, flags, effort, tier in (
                    ("docs", 0, [], "low", "V0"),
                    ("subsystem", 0, [], "low", "V2"),
                    ("subsystem", 2, [], "medium", "V2"),
                    ("subsystem", 0, ["financial"], "high", "V4"),
                ):
                    coordinator["areas"] = [area]
                    coordinator["risk"]["ambiguity"] = ambiguity
                    coordinator["risk"]["critical_flags"] = flags
                    routed = task.route(coordinator)
                    self.assertEqual(routed["model"], "gpt-6-astra")
                    self.assertEqual(routed["reasoning"], effort)
                    self.assertEqual(routed["minimum_verification"], tier)
                    self.assertEqual(routed["required_review"], bool(flags))
                prepared = task.load(state)
                rendered = task.prompt(prepared)
                self.assertIn("CODEX_WORKFLOW_POLICY_V3_MN", rendered)
                self.assertIn('"dirty_ownership"', rendered)
                self.assertNotIn("LOADED REQUIRED SKILL", rendered)
                normal = copy.deepcopy(prepared)
                normal["packet"]["areas"] = ["subsystem"]
                normal["route"] = task.route(normal["packet"])
                body = task.CODE_WORK.read_text()
                self.assertEqual(task.prompt(normal).count(body), 1)
                critical_state = copy.deepcopy(normal)
                critical_state["packet"]["risk"]["critical_flags"] = ["concurrency"]
                critical_state["route"] = task.route(critical_state["packet"])
                self.assertEqual(
                    task.prompt(critical_state), task.legacy_prompt(critical_state)
                )
                critical = copy.deepcopy(packet)
                critical["risk"]["critical_flags"] = ["idempotency"]
                self.assertEqual(task.route(critical)["minimum_verification"], "V3")
                financial = copy.deepcopy(critical)
                financial["risk"]["critical_flags"] = ["financial"]
                self.assertEqual(task.route(financial)["minimum_verification"], "V4")
                critical["frozen_decision"] = {
                    "evidence": {
                        "path": "sample.txt",
                        "sha256": task.digest(root / "sample.txt"),
                    },
                    "open_questions": [],
                    "deterministic_implementation": True,
                }
                self.assertEqual(task.route(critical)["reasoning"], "medium")
                self.assertEqual(task.route(critical)["minimum_verification"], "V3")
                critical["role"] = "review"
                with self.assertRaises(ValueError):
                    task.route(critical)
                self.assertIn("text", task.read_file(state, "sample.txt", 1, 2))
                self.assertTrue(task.read_file(state, "sample.txt", 1, 2)["reused"])
                with self.assertRaises(ValueError):
                    task.scoped(root, "../outside")
                self.assertEqual(task.check(state, "check")["exit"], 0)
                with self.assertRaises(ValueError):
                    task.check(state, "check")
                self.assertEqual(task.close(state)["qualification"], "LOCAL_PLAN_PASS")
                args = [
                    "codex_task.py",
                    "check",
                    "--state",
                    str(state),
                    "check",
                    "--reason",
                    "contract_rerun",
                    "--new-information",
                    "CLI summary contract validation",
                ]
                output = io.StringIO()
                with (
                    patch.object(sys, "argv", args),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(task.main(), 0)
                self.assertNotIn("fingerprint", json.loads(output.getvalue()))
                self.assertIn("fingerprint", task.load(state)["attempts"][-1])
                saved = task.load(state)
                saved["attempts"].append({**saved["attempts"][-1], "exit": 1})
                task.save(state, saved)
                self.assertEqual(task.close(state)["qualification"], "HOLD")
                (root / "sample.txt").write_text("changed\n")
                with self.assertRaises(ValueError):
                    task.resume(state)
                self.assertEqual(task.close(state)["qualification"], "HOLD")
                saved["route"]["model"] = "gpt-6-astra"
                task.save(state, saved)
                with self.assertRaises(ValueError):
                    task.task_state(state)
                with self.assertRaises(ValueError):
                    task.batch([], "codex", 3, "")
                with self.assertRaises(ValueError):
                    task.batch([state, state], "codex", 2, "")
            finally:
                source.unlink(missing_ok=True)
                state.unlink(missing_ok=True)
                for log in root.parent.glob(root.name + "-state-*.log"):
                    log.unlink()

    def test_batch_collects_once(self) -> None:
        state = {"packet": {"independent": True, "role": "review"}}
        with (
            patch.object(task, "task_state", return_value=state),
            patch.object(
                task, "launch", side_effect=lambda p, b: {"exit": 0, "path": str(p)}
            ) as launcher,
        ):
            result = task.batch([Path("one"), Path("two")], "codex", 2, "")
            self.assertEqual(len(result), 2)
            self.assertEqual(launcher.call_count, 2)

    def test_benchmark_failure_is_nonzero_without_model_calls(self) -> None:
        for quality, expected in (("PASS", 0), ("FAIL", 1)):
            with tempfile.TemporaryDirectory() as directory:
                args = [
                    "benchmark_codex.py",
                    "--codex",
                    "never-executed",
                    "--output",
                    str(Path(directory) / "result"),
                    "--run",
                    "--case",
                    "normal",
                    "--variant",
                    "after",
                ]
                with (
                    patch.object(benchmark, "CASES", {"normal": None}),
                    patch.object(
                        benchmark,
                        "run_case",
                        return_value={
                            "case": "normal",
                            "variant": "test",
                            "quality": quality,
                            "exit": 0,
                        },
                    ) as run,
                    patch.object(sys, "argv", args),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(benchmark.main(), expected)
                    run.assert_called_once_with(
                        "normal", "after", Path(directory) / "result", "never-executed"
                    )

        with (
            patch.object(benchmark, "run_case") as run,
            patch.object(
                sys,
                "argv",
                [
                    "benchmark_codex.py",
                    "--codex",
                    "unused",
                    "--output",
                    "/tmp/unused",
                    "--run",
                ],
            ),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as error:
                benchmark.main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_offline_usage_deduplicates_response_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            record: dict[str, Any] = {
                "type": "token_usage_record",
                "payload": {
                    "response_id": "same",
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 60,
                        "output_tokens": 2,
                    },
                },
            }
            started = {"type": "event_msg", "payload": {"type": "task_started"}}
            next_turn = copy.deepcopy(record)
            next_turn["payload"]["response_id"] = "resumed"
            path.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (started, record, record, started, next_turn)
                )
                + "\n"
            )
            result = analyze(path)
            self.assertEqual(result["model_requests"], 1)
            self.assertEqual(result["total_usage"]["uncached_input_tokens"], 40)

    def test_bridge_preserves_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "AGENTS.md"
            target.write_text("existing\n" + task.BRIDGE + "\nuser suffix\n")
            with (
                patch.object(task, "ROOT", root),
                patch.object(task, "BRIDGES", ("AGENTS.md",)),
            ):
                task.bridge(False)
                self.assertTrue(target.read_text().endswith("user suffix\n"))
                self.assertEqual(task.bridge(True)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
