"""Guardrails for the separate offline SQLite Docker Compose lab."""

from pathlib import Path


def test_lab_compose_is_isolated_and_not_a_production_runner():
    text = (Path(__file__).resolve().parents[1] / "docker-compose.sqlite-lab.yaml").read_text()
    required = (
        'profiles: ["sqlite-lab"]', 'network_mode: "none"', 'read_only: true',
        'cap_drop: ["ALL"]', 'no-new-privileges:true',
        'SQLITE_LAB_DIR:?', 'SQLITE_LAB_UID:?', 'SQLITE_LAB_GID:?',
        'target: /workspace', 'target: /lab', 'PYTHONDONTWRITEBYTECODE',
        'entrypoint: ["python", "-c"',
    )
    for token in required:
        assert token in text
    for forbidden in (
        "/app/logs", "/media", "docker.sock", "privileged: true",
        "main.py", "collection_auditor.py", "ALLOW_FILESYSTEM_DELETE",
        "ALLOW_PERMANENT_DELETE", "ports:", "build:",
    ):
        assert forbidden not in text
