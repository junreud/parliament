"""Avoid repeating full projection recovery during unchanged factory plans."""

from test_graphrag_engine import make_factory

from parliament_worker.graphrag.prompts import PROMPT_VERSION


def test_plan_rechecks_saved_projections_only_on_first_plan_or_model_return(
    tmp_path, monkeypatch
) -> None:
    """Recover at startup and on model return, not on each idle plan."""
    factory, _ = make_factory(tmp_path)
    recovery_calls: list[dict[str, bool]] = []
    monkeypatch.setattr(
        factory,
        "recover_projections",
        lambda **options: recovery_calls.append(options),
    )

    factory.plan()
    factory.plan()
    assert recovery_calls == [{"reactivate_cached": False}]

    factory.store.put_artifact(
        "control",
        "model",
        {},
        {"model_signature": "older-model", "prompt_version": PROMPT_VERSION},
    )
    factory.plan()
    assert recovery_calls[-1] == {"reactivate_cached": True}
