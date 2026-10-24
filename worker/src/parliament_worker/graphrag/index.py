"""Incremental graph projections and remotely assigned community hierarchies."""

from collections import defaultdict, deque
from collections.abc import Iterable
from typing import Any

from parliament_worker.graphrag.community_routing import (
    ROUTING_VERSION,
)
from parliament_worker.graphrag.community_routing import (
    bounded_groups as _bounded_groups,
)
from parliament_worker.graphrag.community_routing import report_anchors
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.prompts import (
    GROUP_ID_VERSION,
    PROMPT_VERSION,
    community_task,
    extraction,
)
from parliament_worker.graphrag.source_entities import source_only_person_nodes
from parliament_worker.graphrag.store import GraphStore
from parliament_worker.graphrag.store_bulk import retire_results


def source_dependency(source: dict[str, Any]) -> dict[str, Any]:
    """Pin recurring content to the observation generation, not only its hash."""
    return {key: source[key] for key in ("scope", "fingerprint", "generation")}


def source_manifest(sources: Iterable[dict[str, Any]]) -> str:
    """Fingerprint the complete active source set in scope order."""
    return fingerprint(
        [
            source_dependency(source)
            for source in sorted(sources, key=lambda s: s["scope"])
        ]
    )


def dependencies_current(
    dependency: dict[str, Any], sources: dict[str, dict[str, Any]]
) -> bool:
    """Retire stale descendants before their asynchronous replacement finishes."""
    manifest = dependency.get("source_manifest")
    if manifest is not None and (
        not isinstance(manifest, str) or source_manifest(sources.values()) != manifest
    ):
        return False
    return all(
        sources.get(item["scope"], {}).get("fingerprint") == item["fingerprint"]
        and sources[item["scope"]]["generation"] == item["generation"]
        for item in dependency.get("sources", [])
    )


def routing_current(kind: str, dependency: dict[str, Any]) -> bool:
    """Keep only parents produced by the current candidate-routing contract."""
    return kind != "community" or (
        dependency.get("group_id_version") == GROUP_ID_VERSION
        and (
            not any(
                child.get("kind") == "community"
                for child in dependency.get("children", [])
            )
            or dependency.get("routing_version") == ROUTING_VERSION
        )
    )


def current_artifacts(store: GraphStore, kind: str) -> list[dict[str, Any]]:
    """Return usable current artifacts only, guarding corrections and removals."""
    graphs = store.artifacts("graph")
    needs_communities = kind == "community" or any(
        child.get("kind") == "community"
        for graph in graphs
        for child in graph["dependency"].get("children", [])
    )
    return select_snapshot_artifacts(
        {
            "sources": store.sources(include_payload=False),
            "model": store.get_artifact("control", "model"),
            "artifacts": {
                "graph": graphs,
                "community": store.artifacts("community") if needs_communities else [],
            },
        },
        kind,
    )


def select_snapshot_artifacts(
    snapshot: dict[str, Any], kind: str
) -> list[dict[str, Any]]:
    """Filter graph/report revisions against one captured source and model state.

    Args:
        snapshot: Sources, active model, and candidate current artifacts.
        kind: Graph or community artifact family to return.

    Returns:
        Artifacts whose source, model, and child versions are all current.
    """
    sources = {source["scope"]: source for source in snapshot["sources"]}
    active_model = snapshot["model"]
    snapshots = {
        (item["kind"], item["key"]): item
        for family in ("graph", "community")
        for item in snapshot["artifacts"][family]
    }

    def valid(dependency: dict[str, Any], artifact_kind: str, level: int = 0) -> bool:
        if (
            level > 9
            or not dependencies_current(dependency, sources)
            or not routing_current(artifact_kind, dependency)
        ):
            return False
        if (
            active_model
            and dependency.get("model_signature")
            and (
                dependency["model_signature"]
                != active_model["payload"]["model_signature"]
                or dependency.get("prompt_version", PROMPT_VERSION)
                != active_model["payload"]["prompt_version"]
            )
        ):
            return False
        for child in dependency.get("children", []):
            item = snapshots.get((child["kind"], child["key"]))
            if (
                not item
                or item["version"] != child["version"]
                or not valid(item["dependency"], item["kind"], level + 1)
            ):
                return False
        return True

    return [
        artifact
        for artifact in snapshot["artifacts"][kind]
        if valid(artifact["dependency"], artifact["kind"])
    ]


def children_current(
    store: GraphStore,
    dependency: dict[str, Any],
    *,
    snapshots: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> bool:
    """Reject a late community result whose graph/report input was superseded."""
    for child in dependency.get("children", []):
        current = (
            store.get_artifact(child["kind"], child["key"])
            if snapshots is None
            else snapshots.get((child["kind"], child["key"]))
        )
        if (
            not current
            or current["version"] != child["version"]
            or not routing_current(child["kind"], current["dependency"])
        ):
            return False
    return True


def reconcile(store: GraphStore) -> int:
    """Invalidate outdated work/results without deleting their immutable history."""
    sources = {
        source["scope"]: source for source in store.sources(include_payload=False)
    }
    families = {
        kind: store.artifacts(kind)
        for kind in ("graph", "community", "answer_map", "answer")
    }
    snapshots = {
        (kind, artifact["key"]): artifact
        for kind, artifacts in families.items()
        for artifact in artifacts
    }
    stale_artifacts = []
    for kind, artifacts in families.items():
        for artifact in artifacts:
            if (
                not dependencies_current(artifact["dependency"], sources)
                or not routing_current(kind, artifact["dependency"])
                or not children_current(
                    store, artifact["dependency"], snapshots=snapshots
                )
            ):
                stale_artifacts.append((kind, artifact["key"]))
                snapshots.pop((kind, artifact["key"]), None)
    stale_jobs = []
    for job in store.jobs():
        if job["state"] != "obsolete" and (
            not dependencies_current(job["context"], sources)
            or not routing_current(job["kind"], job["context"])
            or not children_current(store, job["context"], snapshots=snapshots)
        ):
            if job["lease_owner"]:
                continue
            stale_jobs.append(job["id"])
    return retire_results(store, stale_artifacts, stale_jobs)


def plan_extractions(
    store: GraphStore, model_signature: str, capacity: int = 256
) -> int:
    """Bound the pending queue and gradually cover every active source unit."""
    existing = {job["id"]: job for job in store.jobs()}
    room = capacity - sum(
        job["state"] in {"planned", "deferred", "submitting", "polling"}
        for job in existing.values()
    )
    if room <= 0:
        return 0
    planned = []
    known_keys = {(job["kind"], job["key"]) for job in existing.values()}
    for source in store.sources():
        for unit in source["payload"]["units"]:
            key = fingerprint(
                [source_dependency(source), unit["id"], model_signature, PROMPT_VERSION]
            )
            if ("extract", key) in known_keys:
                continue
            body, context = extraction(source, unit)
            context.update(
                sources=[source_dependency(source)],
                artifact_key=source["scope"] + ":" + unit["id"],
                model_signature=model_signature,
                prompt_version=PROMPT_VERSION,
            )
            planned.append(
                {"kind": "extract", "key": key, "request": body, "context": context}
            )
            if len(planned) >= room:
                store.enqueue_many(planned)
                return len(planned)
    if planned:
        store.enqueue_many(planned)
    return len(planned)


def graph_view(
    store: GraphStore, root: str | None = None, depth: int = 2, limit: int = 100
) -> dict[str, Any]:
    """Project a bounded candidate graph; nothing here is a public approval."""
    if not 1 <= depth <= 2 or not 1 <= limit <= 100:
        raise ValueError("invalid graph bounds")
    nodes, edges = {}, {}
    artifacts = current_artifacts(store, "graph")
    for artifact in artifacts:
        for node in artifact["payload"]["nodes"]:
            prior = nodes.get(node["id"])
            if prior and (prior["name"], prior["kind"]) != (node["name"], node["kind"]):
                nodes[node["id"]] = {**prior, "identityConflict": True}
            else:
                nodes[node["id"]] = node
        edges.update({edge["id"]: edge for edge in artifact["payload"]["edges"]})
    for identifier, person in source_only_person_nodes(store.sources()).items():
        nodes.setdefault(identifier, person)
    chosen = set()
    if root:
        if root not in nodes:
            return {
                "nodes": [],
                "edges": [],
                "private": True,
                "truncated": False,
                "coverage": store.status(),
            }
        neighbors: dict[str, set[str]] = defaultdict(set)
        for edge in edges.values():
            neighbors[edge["source"]].add(edge["target"])
            neighbors[edge["target"]].add(edge["source"])
        queue = deque([(root, 0)])
        while queue:
            node, distance = queue.popleft()
            if node in chosen:
                continue
            chosen.add(node)
            if distance < depth:
                queue.extend((item, distance + 1) for item in sorted(neighbors[node]))
    else:
        chosen = set(nodes)
    truncated = len(chosen) > limit
    ordered = ([root] if root else []) + [
        item for item in sorted(chosen) if item != root
    ]
    visible = set(ordered[:limit])
    selected_edges = [
        edge
        for edge in edges.values()
        if edge["source"] in visible and edge["target"] in visible
    ]
    return {
        "nodes": [nodes[key] for key in ordered[:limit]],
        "edges": selected_edges[:1000],
        "private": True,
        "truncated": truncated or len(selected_edges) > 1000,
        "coverage": {
            **store.status(),
            "indexed_units": len(artifacts),
            "graph_nodes": len(nodes),
            "graph_edges": len(edges),
            "source_only_nodes": sum(
                bool(node.get("sourceOnly")) for node in nodes.values()
            ),
        },
    }


def _merge_dependencies(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {}
    for artifact in artifacts:
        for source in artifact["dependency"].get("sources", []):
            unique[source["scope"]] = source
    return [unique[key] for key in sorted(unique)]


def _windows(artifacts: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Create stable bounded planning buckets; the model assigns communities."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in artifacts:
        if not artifact["payload"]["nodes"]:
            continue
        scope = artifact["dependency"]["sources"][0]["scope"]
        buckets[fingerprint(scope)[:2]].append(artifact)
    result = []
    for bucket, values in sorted(buckets.items()):
        for artifact in sorted(values, key=lambda item: item["key"]):
            # Each fixed unit supplies an overlap window; membership is semantic
            # model output, not this deterministic transport partition.
            result.append((f"leaf:{bucket}:{fingerprint(artifact['key'])}", [artifact]))
    return result


def _community_input(
    artifacts: list[dict[str, Any]], level: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    members, proofs = {}, {}
    for artifact in artifacts:
        if level == 0:
            for node in artifact["payload"]["nodes"]:
                members[node["id"]] = node
            for edge in artifact["payload"]["edges"]:
                for proof in edge["evidence"]:
                    proofs[fingerprint(proof)] = proof
        else:
            for group in artifact["payload"]["groups"]:
                members[group["id"]] = {
                    "id": group["id"],
                    "title": group["title"],
                    "summary": group["summary"],
                }
                for claim in group["claims"]:
                    proofs[fingerprint(claim["evidence"])] = claim["evidence"]
    return list(members.values()), list(proofs.values())


def plan_communities(
    store: GraphStore, model_signature: str, capacity: int = 256
) -> int:
    """Build remotely inferred leaf memberships and hierarchical community reports."""
    graphs = current_artifacts(store, "graph")
    if not graphs:
        return 0
    graph_keys = {artifact["key"] for artifact in graphs}
    awaiting_graphs = any(
        f"{source['scope']}:{unit['id']}" not in graph_keys
        for source in store.sources()
        for unit in source["payload"]["units"]
    )
    jobs = store.jobs()
    room = capacity - sum(
        job["state"] in {"planned", "deferred", "submitting", "polling"} for job in jobs
    )
    known = {(job["kind"], job["key"]) for job in jobs}
    community_artifacts = store.artifacts("community")
    reports = {artifact["key"]: artifact for artifact in community_artifacts}
    planned = []
    windows = _windows(graphs)
    level = 0
    live_keys = set()
    expected_leaves = {key for key, _ in windows}
    hierarchy_complete = False
    stale_reports = set()
    anchors_by_key: dict[str, frozenset[str]] = {}
    while windows and level <= 8:
        next_level = []
        for logical_key, inputs in windows:
            live_keys.add(logical_key)
            dependency = {
                "sources": _merge_dependencies(inputs),
                "children": [
                    {
                        "kind": item["kind"],
                        "key": item["key"],
                        "version": item["version"],
                    }
                    for item in inputs
                ],
                "model_signature": model_signature,
                "prompt_version": PROMPT_VERSION,
                "group_id_version": GROUP_ID_VERSION,
            }
            if level > 0:
                dependency["routing_version"] = ROUTING_VERSION
            key = fingerprint([logical_key, dependency])
            artifact = reports.get(logical_key)
            if artifact and artifact["dependency"] == dependency:
                anchors_by_key[logical_key] = report_anchors(artifact, anchors_by_key)
                next_level.append(artifact)
                continue
            if ("community", key) in known:
                cached = [
                    version
                    for version in store.artifact_versions("community", logical_key)
                    if version["dependency"] == dependency
                ]
                if cached:
                    restored = cached[-1]
                    store.put_artifact(
                        "community", logical_key, dependency, restored["payload"]
                    )
                    restored = {**restored, "current": True}
                    reports[logical_key] = restored
                    anchors_by_key[logical_key] = report_anchors(
                        restored, anchors_by_key
                    )
                    next_level.append(restored)
                    continue
            if artifact:
                stale_reports.add(logical_key)
            if ("community", key) in known or len(planned) >= room:
                continue
            members, proofs = _community_input(inputs, level)
            if not members:
                continue
            try:
                links = [
                    edge for item in inputs for edge in item["payload"].get("edges", [])
                ]
                body, context = community_task(
                    members, proofs, level=level, links=links
                )
            except ValueError:
                # Oversized evidence is visible rather than silently summarized.
                # Extraction units are bounded; context failures need review.
                store.put_artifact(
                    "review",
                    logical_key,
                    dependency,
                    {"error": "community_context_limit", "public": False},
                )
                continue
            context.update(dependency, artifact_key=logical_key)
            planned.append(
                {"kind": "community", "key": key, "request": body, "context": context}
            )
        if level == 0 and (
            awaiting_graphs or {item["key"] for item in next_level} != expected_leaves
        ):
            break
        if len(next_level) != len(windows):
            break
        if len(next_level) <= 1:
            hierarchy_complete = True
            break
        level += 1
        groups = _bounded_groups(next_level, level, anchors_by_key)
        linked_groups = [group for group in groups if len(group) > 1]
        if not linked_groups:
            hierarchy_complete = True
            break
        windows = [
            (
                f"parent:{level}:{fingerprint([item['key'] for item in group])}",
                group,
            )
            for group in linked_groups
        ]
    # A missing graph window must not leave its reports searchable.
    for artifact in community_artifacts:
        if (
            artifact["key"].startswith("leaf:")
            and artifact["key"] not in expected_leaves
        ) or (hierarchy_complete and artifact["key"] not in live_keys):
            stale_reports.add(artifact["key"])
    retire_results(store, [("community", key) for key in sorted(stale_reports)])
    if planned:
        store.enqueue_many(planned)
    return len(planned)
