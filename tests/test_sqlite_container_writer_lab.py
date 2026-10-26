"""Fixture availability is useful only when write denial is actually observed."""
import errno
import hashlib
from pathlib import Path
import urllib.error

import pytest

from scripts import sqlite_container_writer_lab as lab


def fixture(tmp_path):
    media, state = tmp_path / "media", tmp_path / "state"
    for root in (media, state):
        root.mkdir()
        (root / ".disposable_container_writer").write_bytes(lab.MARKER)
    (state / "reads").write_text("0")
    (media / "payload.bin").write_bytes(b"INITIAL\n")
    return lab.Fixture(media, state)


def test_read_requests_advance_app_state_without_changing_media(tmp_path):
    service = fixture(tmp_path)
    before = (service.media / "payload.bin").read_bytes()
    first, second = service.read(), service.read()
    assert second["request_sequence"] > first["request_sequence"]
    assert second["protection"] == "keep"
    assert (service.media / "payload.bin").read_bytes() == before
    assert (service.state / "reads").read_text() == "2"


def test_writable_baseline_changes_only_the_fixed_disposable_payload(tmp_path):
    service = fixture(tmp_path)
    assert service.write(lab.BEFORE) == (200, {"status": "fixture_written"})
    assert (service.media / "payload.bin").read_bytes() == lab.BEFORE
    assert service.write(b"unknown") == (400, {"status": "invalid_fixture_request"})
    assert (service.media / "payload.bin").read_bytes() == lab.BEFORE


def test_read_only_failure_is_reported_only_for_erofs(tmp_path, monkeypatch):
    service = fixture(tmp_path)
    original = Path.write_bytes
    def denied(path, data):
        if path == service.media / "payload.bin":
            raise OSError(errno.EROFS, "read-only fixture")
        return original(path, data)
    monkeypatch.setattr(Path, "write_bytes", denied)
    assert service.write(lab.DENIED) == (409, {"status": "write_denied", "errno": errno.EROFS})
    assert (service.media / "payload.bin").read_bytes() == b"INITIAL\n"


def test_other_io_failures_are_not_evidence_of_read_only_policy(tmp_path, monkeypatch):
    service = fixture(tmp_path)
    def denied(path, data):
        raise PermissionError(errno.EACCES, "permission failure")
    monkeypatch.setattr(Path, "write_bytes", denied)
    with pytest.raises(PermissionError):
        service.write(lab.DENIED)


def test_lost_marker_blocks_both_fixture_reads_and_writes(tmp_path):
    service = fixture(tmp_path)
    (service.media / ".disposable_container_writer").write_bytes(b"changed")
    for operation in (service.read, lambda: service.write(lab.DENIED)):
        with pytest.raises(RuntimeError, match="fixture required"):
            operation()
    assert (service.state / "reads").read_text() == "0"
    assert (service.media / "payload.bin").read_bytes() == b"INITIAL\n"


def read_response(sequence):
    return 200, {"protection": "keep", "request_sequence": sequence,
                 "media_digest": hashlib.sha256(lab.BEFORE).hexdigest()}


def test_ro_client_requires_erofs_and_fresh_reads_without_authorizing_production(monkeypatch):
    replies = iter([read_response(1), (409, {"status": "write_denied", "errno": errno.EROFS}),
                    read_response(2)])
    calls = []
    def request(path, data=None):
        calls.append((path, data))
        return next(replies)
    monkeypatch.setattr(lab, "request", request)
    report = lab.check(True)
    assert calls == [("/protection", None), ("/fixture-write", lab.DENIED), ("/protection", None)]
    assert report["status"] == "read_only_media_verified"
    assert report["writer_exclusion_verified"] is False
    assert report["production_authorized"] is False


@pytest.mark.parametrize("response", [(200, {"status": "fixture_written"}),
                                      (409, {"status": "write_denied", "errno": errno.EACCES}),
                                      (500, {"status": "fixture_write_failed"})])
def test_ro_client_does_not_accept_writes_or_unrelated_errors(monkeypatch, response):
    replies = iter([read_response(1), response])
    monkeypatch.setattr(lab, "request", lambda *args: next(replies))
    with pytest.raises(RuntimeError, match="write outcome"):
        lab.check(True)


def test_uncertain_write_is_never_retried(monkeypatch):
    calls = []
    def request(path, data=None):
        calls.append((path, data))
        if data is not None:
            raise urllib.error.URLError("uncertain write")
        return read_response(1)
    monkeypatch.setattr(lab, "request", request)
    with pytest.raises(urllib.error.URLError):
        lab.check(True)
    assert len(calls) == 2
    assert sum(data is not None for _, data in calls) == 1


def test_cached_fixture_response_fails_acceptance(monkeypatch):
    replies = iter([read_response(1), (409, {"status": "write_denied", "errno": errno.EROFS}),
                    read_response(1)])
    monkeypatch.setattr(lab, "request", lambda *args: next(replies))
    with pytest.raises(RuntimeError, match="read after write"):
        lab.check(True)
