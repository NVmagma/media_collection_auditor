"""Guardrails for the separate offline SQLite Docker Compose lab."""

from pathlib import Path


def test_lab_compose_is_isolated_and_not_a_production_runner():
    text = (Path(__file__).resolve().parents[1] / "docker-compose.sqlite-lab.yaml").read_text()
    required = (
        'profiles: ["sqlite-lab"]', 'SQLITE_LAB_IMAGE:?', 'network_mode: "none"', 'read_only: true',
        'cap_drop: ["ALL"]', 'no-new-privileges:true',
        'SQLITE_LAB_DIR:?', 'SQLITE_LAB_UID:?', 'SQLITE_LAB_GID:?',
        'target: /workspace', 'target: /lab', 'PYTHONDONTWRITEBYTECODE',
        'entrypoint: ["python"]', 'command: ["-c"',
    )
    for token in required:
        assert token in text
    for forbidden in (
        "/app/logs", "/media", "docker.sock", "privileged: true",
        "main.py", "collection_auditor.py", "ALLOW_FILESYSTEM_DELETE",
        "ALLOW_PERMANENT_DELETE", "ports:", "build:",
    ):
        assert forbidden not in text


def test_bind_mounts_cannot_create_missing_host_directories():
    """Compose must refuse absent paths rather than creating host directories."""
    text = (Path(__file__).resolve().parents[1] / "docker-compose.sqlite-lab.yaml").read_text()
    assert text.count("create_host_path: false") == 2
    assert "create_host_path: true" not in text


def test_explicit_module_command_does_not_use_placeholder_entrypoint():
    text = (Path(__file__).resolve().parents[1] / "docker-compose.sqlite-lab.yaml").read_text()
    assert 'entrypoint: ["python"]' in text
    assert 'command: ["-c"' in text
    assert 'entrypoint: ["python", "-c"' not in text
