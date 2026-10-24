"""Real concurrent HTTP dispatch preserves durable budgets and recovery."""

import json
import threading
import time

import httpx
import pytest
from test_graphrag_client import config
from test_graphrag_engine import SIGNATURE, RemoteFixture
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.client import (
    InferenceClient,
    InferenceError,
    canonical_body,
)
from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.store import GraphStore


def configured_factory(tmp_path, remote, count, **limits):
    """Plan a fixed source set without touching an external server."""
    store = GraphStore(tmp_path / "parallel")
    sources = []
    for index in range(count):
        batch = fixture_batch()
        batch["documents"][0]["recordKey"] = str(index)
        sources.extend(sources_from_batch(batch))
    store.put_sources(sources)
    factory = Factory(store, remote, SIGNATURE, poll_seconds=60, **limits)
    factory.plan()
    return factory


def test_dns_deferrals_release_remote_slots_for_untried_requests(tmp_path):
    """A pre-acceptance DNS error must not occupy the remote concurrency window."""

    class DnsUnavailable:
        def __init__(self):
            self.calls = []

        def submit(self, body, key):
            self.calls.append(key)
            raise InferenceError("inference_dns_unavailable", retryable=True)

    remote = DnsUnavailable()
    factory = configured_factory(
        tmp_path,
        remote,
        5,
        concurrency=2,
        daily_jobs=0,
        daily_tokens=0,
    )

    factory.tick(2)
    assert len(remote.calls) == 2
    for job in factory.store.jobs(state="deferred"):
        factory.store.update_job(job["id"], next_poll=time.time() + 3600)
    factory.tick(2)

    assert len(remote.calls) == 4
    assert len(factory.store.jobs(state="planned")) == 1


@pytest.mark.parametrize("concurrency", [16, 32, 64])
def test_http_submissions_and_polls_really_overlap(tmp_path, concurrency):
    barrier = threading.Barrier(concurrency, timeout=2)
    lock = threading.Lock()
    active = peak = 0
    calls = []
    persisted = {}
    model = RemoteFixture()

    def transport(request):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append((request.method, str(request.url)))
        try:
            if request.method == "POST":
                key = request.headers["Idempotency-Key"]
                assert persisted[key]["state"] == "submitting"
                assert persisted[key]["attempts"] == 1
                assert canonical_body(persisted[key]["request"]) == request.content
                model.accepted[key] = json.loads(request.content)
                barrier.wait()
                return httpx.Response(202, json={"request_id": key, "state": "queued"})
            barrier.wait()
            key = request.url.path.rsplit("/", 1)[1]
            return httpx.Response(
                200,
                json={"request_id": key, **model.poll(key)},
                headers={
                    "X-Model-Repo": "test-model",
                    "X-Model-Revision": "test-revision",
                },
            )
        finally:
            with lock:
                active -= 1

    client = InferenceClient(config(), transport=httpx.MockTransport(transport))
    factory = configured_factory(
        tmp_path, client, concurrency + 4, concurrency=concurrency
    )

    # Capture the durable state at HTTP entry; all selected intentions must exist.
    def snapshot_transport(request):
        if request.method == "POST" and not persisted:
            with lock:
                if not persisted:
                    persisted.update(
                        (job["idempotency_key"], job) for job in factory.store.jobs()
                    )
        return transport(request)

    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(snapshot_transport))
    try:
        assert factory.tick(max(32, concurrency)) == concurrency
        assert peak == concurrency
        assert len(calls) == concurrency
        assert len(factory.store.jobs(state="polling")) == concurrency
        for job in factory.store.jobs(state="polling"):
            factory.store.update_job(job["id"], next_poll=0)
        peak = 0
        assert factory.tick(concurrency) == concurrency
        assert peak == concurrency
        assert len(factory.store.jobs(state="completed")) == concurrency
        assert len([call for call in calls if call[0] == "POST"]) == concurrency
    finally:
        client.close()


def test_one_uncertain_submission_preserves_other_concurrent_receipts(tmp_path):
    barrier = threading.Barrier(4, timeout=2)
    lock = threading.Lock()
    accepted = []

    def transport(request):
        with lock:
            position = len(accepted)
            accepted.append(request.headers["Idempotency-Key"])
        barrier.wait()
        if position == 0:
            raise httpx.ReadTimeout("receipt lost")
        return httpx.Response(
            202, json={"request_id": accepted[position], "state": "queued"}
        )

    client = InferenceClient(config(), transport=httpx.MockTransport(transport))
    factory = configured_factory(tmp_path, client, 8, concurrency=4)
    try:
        factory.tick(8)
        assert len(accepted) == 4
        assert len(factory.store.jobs(state="polling")) == 3
        unknown = factory.store.jobs(state="deferred")
        assert len(unknown) == 1 and unknown[0]["remote_id"] is None
        assert factory.store.get_artifact("control", "pause") is not None
        factory.resume()
        factory.store.update_job(unknown[0]["id"], next_poll=0)
        assert factory.tick(4) == 0
        assert len(accepted) == 4
    finally:
        client.close()


@pytest.mark.parametrize("daily_jobs,daily_tokens", [(2, 0), (0, 4096)])
def test_parallel_batch_respects_daily_reservations(tmp_path, daily_jobs, daily_tokens):
    remote = RemoteFixture()
    factory = configured_factory(
        tmp_path,
        remote,
        8,
        concurrency=8,
        daily_jobs=daily_jobs,
        daily_tokens=daily_tokens,
    )
    factory.tick(8)
    submitted = [
        job for job in factory.store.jobs() if job["metadata"].get("submitted_day")
    ]
    if daily_jobs:
        assert len(submitted) == daily_jobs
    else:
        assert (
            sum(job["metadata"]["reserved_tokens"] for job in submitted) <= daily_tokens
        )
        assert submitted
    assert len(remote.submissions) == len(submitted)


def test_durable_pre_http_uncertainty_blocks_crash_replay(tmp_path):
    remote = RemoteFixture()
    factory = configured_factory(tmp_path, remote, 1, concurrency=4)

    def assert_intent(body, key):
        job = factory.store.jobs()[0]
        assert job["state"] == "submitting"
        assert job["metadata"].get("completion_uncertain") is True
        return {"request_id": key, "state": "queued"}

    remote.submit = assert_intent
    factory.tick(1)
    assert factory.store.jobs()[0]["metadata"]["completion_uncertain"] is False


def test_slow_completed_wave_renews_remaining_leases(tmp_path, monkeypatch):
    """Long local validation must not expire later receipts in one HTTP wave."""
    from parliament_worker.graphrag import execution

    remote = RemoteFixture()
    factory = configured_factory(tmp_path, remote, 2, concurrency=2)
    assert factory.tick(2) == 2
    for job in factory.store.jobs(state="polling"):
        factory.store.update_job(job["id"], next_poll=0)
    monkeypatch.setattr(execution, "WAVE_LEASE_SECONDS", 0.5)
    original = factory._complete

    def slow_complete(job, response, now):
        time.sleep(0.3)
        original(job, response, now)

    monkeypatch.setattr(factory, "_complete", slow_complete)
    assert factory.tick(2) == 2
    assert len(factory.store.jobs(state="completed")) == 2


def test_invalid_output_in_slow_wave_does_not_lose_later_result(tmp_path, monkeypatch):
    """A rejected model result must not expire the next completed receipt."""
    from parliament_worker.graphrag import execution

    remote = RemoteFixture()
    factory = configured_factory(tmp_path, remote, 2, concurrency=2)
    assert factory.tick(2) == 2
    for job in factory.store.jobs(state="polling"):
        factory.store.update_job(job["id"], next_poll=0)
    rejected_id = factory.store.jobs(state="polling")[0]["id"]
    monkeypatch.setattr(execution, "WAVE_LEASE_SECONDS", 0.5)
    original = factory._complete

    def complete_or_reject(job, response, now):
        time.sleep(0.3)
        if job["id"] == rejected_id:
            raise ValueError("community membership coverage incomplete")
        original(job, response, now)

    monkeypatch.setattr(factory, "_complete", complete_or_reject)
    assert factory.tick(2) == 2
    assert factory.store.get_job(rejected_id)["error"] == (
        "generated_content_validation_failed"
    )
    assert len(factory.store.jobs(state="completed")) == 1


def test_expired_lease_before_http_does_not_stop_executor(tmp_path, monkeypatch):
    """A stale pre-HTTP lease must not kill unrelated recovery work."""
    remote = RemoteFixture()
    factory = configured_factory(tmp_path, remote, 1, concurrency=4)
    original = factory.store.update_leased

    def expired_once(owner, changes, *, now=None):
        monkeypatch.setattr(factory.store, "update_leased", original)
        raise ValueError("stale graph job lease")

    monkeypatch.setattr(factory.store, "update_leased", expired_once)
    assert factory.tick(1) == 0
    assert not remote.submissions
    assert factory.store.jobs()[0]["state"] == "planned"


def test_crash_after_http_acceptance_never_automatically_resubmits(tmp_path):
    from parliament_worker.graphrag.execution import WAVE_LEASE_SECONDS

    remote = RemoteFixture()
    factory = configured_factory(tmp_path, remote, 1, concurrency=4)

    def crash(body, key):
        remote.accepted[key] = body
        raise RuntimeError("process ended before receipt was saved")

    remote.submit = crash
    with pytest.raises(RuntimeError, match="process ended"):
        factory.tick(1)
    job = factory.store.jobs()[0]
    assert job["metadata"]["completion_uncertain"] is True
    recovered = factory.store.claim(
        "expired-lease-recovery", 120, now=time.time() + WAVE_LEASE_SECONDS + 1
    )
    assert len(recovered) == 1
    factory.store.release(job["id"], "expired-lease-recovery", next_poll=0)
    restarted = Factory(factory.store, remote, SIGNATURE, concurrency=4)
    assert restarted.tick(4) == 0
    assert len(remote.accepted) == 1
    assert factory.store.get_artifact("control", "pause") is not None


def test_source_change_during_http_never_projects_old_result(tmp_path):
    from copy import deepcopy

    from parliament_worker.graphrag.inputs import fingerprint

    remote = RemoteFixture()
    factory = configured_factory(tmp_path, remote, 1, concurrency=4)
    factory.tick(1)
    job = factory.store.jobs()[0]
    factory.store.update_job(job["id"], next_poll=0)
    original = remote.poll

    def corrected_poll(key):
        changed = deepcopy(factory.store.sources()[0])
        changed["payload"]["document"]["version"] = "correction"
        changed["fingerprint"] = fingerprint(changed["payload"])
        factory.store.put_sources([changed])
        return original(key)

    remote.poll = corrected_poll
    assert factory.tick(1) == 1
    assert factory.store.get_job(job["id"])["state"] == "obsolete"
    assert factory.store.artifacts("graph") == []


def test_auth_rejection_drains_already_started_wave_before_pausing(tmp_path):
    barrier = threading.Barrier(4, timeout=2)
    lock = threading.Lock()
    keys = []

    def transport(request):
        key = request.headers["Idempotency-Key"]
        with lock:
            rejected = not keys
            keys.append(key)
        barrier.wait()
        if rejected:
            return httpx.Response(401)
        return httpx.Response(202, json={"request_id": key, "state": "queued"})

    client = InferenceClient(config(), transport=httpx.MockTransport(transport))
    factory = configured_factory(tmp_path, client, 8, concurrency=4)
    try:
        factory.tick(8)
        assert len(keys) == 4
        assert len(factory.store.jobs(state="failed")) == 1
        assert len(factory.store.jobs(state="polling")) == 3
        assert len(factory.store.jobs(state="planned")) == 4
        assert factory.tick(8) == 0
    finally:
        client.close()


def test_leased_batch_changes_are_atomic_on_invalid_owner(tmp_path):
    factory = configured_factory(tmp_path, RemoteFixture(), 2, concurrency=2)
    jobs = factory.store.claim(factory.owner, lease_seconds=120, limit=2)
    factory.store.release(jobs[1]["id"], factory.owner)
    with pytest.raises(ValueError, match="stale graph job lease"):
        factory.store.update_leased(
            factory.owner,
            [(job["id"], {"state": "submitting"}, False) for job in jobs],
        )
    assert factory.store.get_job(jobs[0]["id"])["state"] == "planned"
