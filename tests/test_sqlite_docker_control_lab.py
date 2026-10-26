"""Only fixed private fixture calls; no real daemon API is ever used here."""
import json
from pathlib import Path
import subprocess

import pytest

from scripts import sqlite_docker_control_lab as lab

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/sqlite_docker_control_lab.sh"


class Response:
    def __init__(self, payload, status=200):
        self.status = status
        self.payload = json.dumps(payload).encode()
    def read(self, limit):
        return self.payload


class Connection:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.sock = object()
        self.closed = False
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
    def getresponse(self):
        return self.response
    def close(self):
        self.closed = True


@pytest.mark.parametrize("response", [Response({"message": "real daemon style"}, 404),
                                      Response({"message": "missing fixture identity"})])
def test_private_identity_is_required_before_actor_can_issue_actions(response):
    connection = Connection(response)
    with pytest.raises(RuntimeError):
        lab.request(connection, "GET", "/fixture/status")
    assert len(connection.calls) == 1
    assert connection.calls[0][0][0] == "GET"


def commands(tmp_path, monkeypatch):
    (tmp_path / ".disposable_docker_control").write_bytes(lab.MARKER)
    monkeypatch.setattr(lab, "Path", lambda _: tmp_path)
    return tmp_path


def test_actor_refuses_old_request_markers_before_connecting(tmp_path, monkeypatch):
    root = commands(tmp_path, monkeypatch)
    (root / "request.1").touch()
    def unexpected(path):
        raise AssertionError("Connection must not be attempted")
    monkeypatch.setattr(lab, "UnixConnection", unexpected)
    with pytest.raises(RuntimeError, match="preexisting request"):
        lab.actor()


def test_actor_has_no_retry_or_reconnect_after_uncertain_action(tmp_path, monkeypatch):
    root = commands(tmp_path, monkeypatch)
    connection = Connection(None)
    monkeypatch.setattr(lab, "UnixConnection", lambda _: connection)
    calls = []
    def request(conn, method, path):
        calls.append((method, path))
        if method == "GET":
            return {"fixture": lab.IDENTITY, "calls": 0}
        raise ConnectionResetError("uncertain fixture action")
    monkeypatch.setattr(lab, "request", request)
    monkeypatch.setattr(lab.time, "sleep", lambda _: (root / "request.1").touch())
    with pytest.raises(ConnectionResetError):
        lab.actor()
    assert calls == [("GET", "/fixture/status"), ("POST", "/fixture/start")]
    assert connection.closed


def test_actor_will_not_reconnect_a_lost_established_connection(tmp_path, monkeypatch):
    root = commands(tmp_path, monkeypatch)
    connection = Connection(None)
    monkeypatch.setattr(lab, "UnixConnection", lambda _: connection)
    def request(conn, method, path):
        connection.sock = None
        return {"fixture": lab.IDENTITY, "calls": 0}
    monkeypatch.setattr(lab, "request", request)
    monkeypatch.setattr(lab.time, "sleep", lambda _: (root / "request.1").touch())
    with pytest.raises(RuntimeError, match="connection lost"):
        lab.actor()
    assert connection.closed


@pytest.mark.parametrize("count", ["-1", "3", "bad"])
def test_fixture_counter_is_bounded_and_not_reset(tmp_path, count):
    (tmp_path / "calls").write_text(count)
    with pytest.raises((ValueError, RuntimeError)):
        lab.read_count(tmp_path)
    assert (tmp_path / "calls").read_text() == count


def test_pause_controller_death_has_no_restore_dispatch(tmp_path):
    text = SCRIPT.read_text()
    function = "pause_controller(){\n" + text.split("pause_controller(){\n", 1)[1].split("\n}\npause_controller", 1)[0] + "\n}\n"
    code = '''
lab=$1
actor_id=fixture-only-id
docker(){ printf '%s\\n' "$*" >> "$lab/calls"; }
''' + function + '''
pause_controller &
worker=$!
for attempt in $(seq 1 100); do
  [ ! -f "$lab/controller-paused" ] || break
  sleep 0.01
done
[ -f "$lab/controller-paused" ]
kill -KILL "$worker"
result=0
wait "$worker" 2>/dev/null || result=$?
[ "$result" = 137 ]
'''
    result = subprocess.run(["bash", "-eu", "-s", "--", str(tmp_path)], input=code,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "calls").read_text() == "pause fixture-only-id\n"


@pytest.mark.parametrize("failure", ["none", "daemon", "actor"])
def test_cleanup_ends_endpoint_before_removing_actor_and_never_unpauses(tmp_path, failure):
    text = SCRIPT.read_text()
    function = "cleanup(){\n" + text.split("cleanup(){\n", 1)[1].split("\n}\ntrap cleanup", 1)[0] + "\n}\n"
    code = '''
lab=$1
failure=$2
daemon_id=daemon
actor_id=actor
controller_pid=
docker(){
  printf '%s\\n' "$*" >> "$lab/calls"
  [ "$3" != "$failure" ]
}
''' + function + '\ncleanup\n'
    result = subprocess.run(["bash", "-eu", "-s", "--", str(tmp_path), failure],
                            input=code, text=True, capture_output=True, timeout=10)
    assert result.returncode == (0 if failure == "none" else 2)
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls[0] == "rm -f daemon"
    assert calls == (["rm -f daemon"] if failure == "daemon" else ["rm -f daemon", "rm -f actor"])
