"""The live loop keeps execution moving between bounded planning scans."""

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from parliament_worker.graphrag import cli
from parliament_worker.graphrag.store import GraphStore


def run_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cycles: int,
    plan_seconds: float,
    source_changes: bool = False,
    idle: bool = False,
    busy_plan_once: bool = False,
) -> dict[str, Any]:
    """Run actual coordinator scheduling with a deterministic, non-sleeping clock."""
    counters: dict[str, Any] = {"ticks": 0, "plans": 0, "scans": 0, "waits": []}
    clock = [100.0]

    class StopEvent:
        def is_set(self):
            return counters["ticks"] >= cycles

        def wait(self, seconds):
            counters["waits"].append(seconds)
            clock[0] += seconds

        def set(self):
            counters["ticks"] = cycles

    class PlannedFactory:
        def __init__(self, *args, **kwargs):
            pass

        def recover_projections(self):
            pass

        def sync_inputs(self, *args, **kwargs):
            counters["scans"] += 1
            return {"changed": int(source_changes and counters["scans"] == 2)}

        def plan(self):
            counters["plans"] += 1
            if busy_plan_once and counters["plans"] == 1:
                raise ValueError("pilot store busy")
            return {"extractions": 1}

        def tick(self, max_operations):
            counters["ticks"] += 1
            return 0 if idle else max_operations

        def _paused(self):
            return False

    monkeypatch.setenv("GRAPHRAG_MODEL_REPO", "test-model")
    monkeypatch.setenv("GRAPHRAG_MODEL_REVISION", "test-revision")
    monkeypatch.setattr(cli, "Factory", PlannedFactory)
    monkeypatch.setattr(cli.InferenceConfig, "from_env", lambda: object())
    monkeypatch.setattr(
        cli, "InferenceClient", lambda config: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(cli.threading, "Event", StopEvent)
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cli.signal, "signal", lambda *args: None)
    args = Namespace(
        max_operations=32,
        scan_seconds=5,
        plan_seconds=plan_seconds,
        send=True,
        concurrency=32,
        daily_jobs=0,
        daily_tokens=0,
        queue_capacity=256,
        poll_seconds=0.25,
        api_port=None,
        input=[],
        retire_missing=False,
        forever=True,
    )
    assert cli._work(args, GraphStore(tmp_path)) == 0
    return counters


def test_execution_keeps_running_without_full_plan_before_every_poll(
    tmp_path, monkeypatch
):
    counters = run_loop(tmp_path, monkeypatch, cycles=20, plan_seconds=5)
    assert counters["ticks"] == 20
    assert 1 <= counters["plans"] <= 2


def test_changed_input_triggers_plan_before_normal_interval(tmp_path, monkeypatch):
    counters = run_loop(
        tmp_path, monkeypatch, cycles=40, plan_seconds=300, source_changes=True
    )
    assert counters["ticks"] == 40
    assert counters["plans"] == 2


def test_idle_factory_waits_between_expensive_status_checks(tmp_path, monkeypatch):
    counters = run_loop(tmp_path, monkeypatch, cycles=3, plan_seconds=60, idle=True)
    assert counters["ticks"] == 3
    assert counters["waits"] == [60, 60, 60]


def test_busy_plan_is_deferred_without_stopping_the_factory(tmp_path, monkeypatch):
    counters = run_loop(
        tmp_path, monkeypatch, cycles=3, plan_seconds=60, busy_plan_once=True
    )
    assert counters["ticks"] == 3
    assert counters["plans"] == 2
