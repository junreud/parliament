"""Capture a small, read-only local MySQL inventory for the data landscape."""

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".local/data-landscape/mysql-snapshot.json"
TABLES = (
    "parliament_source_record",
    "parliament_source_record_version",
    "parliament_person",
    "parliament_ingestion_run",
    "knowledge_batch",
    "knowledge_entity",
    "knowledge_document_version",
    "knowledge_evidence",
    "knowledge_relation",
    "tracking_event",
    "tracking_event_version",
)


def _query(container: str, sql: str) -> list[str]:
    """Run a fixed SELECT inside the local container without exporting a secret."""
    command = [
        "docker",
        "exec",
        "-i",
        container,
        "sh",
        "-c",
        'exec mysql -uroot --password="$MYSQL_ROOT_PASSWORD" '
        "--default-character-set=utf8mb4 -N -r -D parliament",
    ]
    result = subprocess.run(
        command,
        input=sql,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("local MySQL inventory query failed")
    return [line for line in result.stdout.splitlines() if line]


def snapshot(container: str) -> dict:
    """Read exact counts plus safe document and batch metadata."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", container):
        raise ValueError("invalid container name")
    counts_sql = (
        " UNION ALL ".join(
            f"SELECT '{table}', COUNT(*) FROM `{table}`" for table in TABLES
        )
        + ";"
    )
    counts = {}
    for line in _query(container, counts_sql):
        name, value = line.split("\t", 1)
        counts[name] = int(value)
    batches_sql = (
        "SELECT JSON_OBJECT('id',batch_id,'issueId',issue_id,"
        "'state',review_state,'createdAt',CAST(created_at AS CHAR)) "
        "FROM knowledge_batch ORDER BY created_at DESC;"
    )
    documents_sql = (
        "SELECT JSON_OBJECT('id',document_id,'title',"
        "JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.title')),'sourceKey',"
        "JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.sourceKey')),'bodyStatus',"
        "JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.bodyStatus')),'licenseStatus',"
        "JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.licenseStatus')),'extractionVersion',"
        "JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.extractionVersion'))) "
        "FROM knowledge_document_version ORDER BY document_id LIMIT 100;"
    )
    extractions_sql = (
        "SELECT JSON_OBJECT('documentId',document_id,'versionId',version_id,"
        "'extractionVersion',extraction_version,'segmentCount',JSON_LENGTH(segments),"
        "'samples',JSON_ARRAY("
        "JSON_OBJECT('locator',LEFT(JSON_UNQUOTE(JSON_EXTRACT(segments,'$[10].locator')),160),"
        "'text',LEFT(JSON_UNQUOTE(JSON_EXTRACT(segments,'$[10].text')),240)),"
        "JSON_OBJECT('locator',LEFT(JSON_UNQUOTE(JSON_EXTRACT(segments,'$[30].locator')),160),"
        "'text',LEFT(JSON_UNQUOTE(JSON_EXTRACT(segments,'$[30].text')),240)),"
        "JSON_OBJECT('locator',LEFT(JSON_UNQUOTE(JSON_EXTRACT(segments,'$[50].locator')),160),"
        "'text',LEFT(JSON_UNQUOTE(JSON_EXTRACT(segments,'$[50].text')),240)))) "
        "FROM knowledge_extraction ORDER BY document_id,extraction_version LIMIT 300;"
    )
    return {
        "schema": "parliament-mysql-landscape-v1",
        "classification": "local_mysql_observation",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "database": "parliament",
        "counts": counts,
        "batches": [json.loads(line) for line in _query(container, batches_sql)],
        "documents": [json.loads(line) for line in _query(container, documents_sql)],
        "extractions": [
            json.loads(line) for line in _query(container, extractions_sql)
        ],
    }


def main() -> None:
    """Save one private snapshot without changing source tables."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="parliament-mysql-1")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    data = snapshot(args.container)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output.parent, 0o700)
    descriptor, temporary = tempfile.mkstemp(dir=output.parent, prefix=".mysql-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    main()
