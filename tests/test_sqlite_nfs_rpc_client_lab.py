import importlib.util
from pathlib import Path
import struct

import pytest


spec = importlib.util.spec_from_file_location("nfs_rpc_fixture", Path(__file__).resolve().parents[1] / "scripts/sqlite_nfs_rpc_client_lab.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class Socket:
    def __init__(self, response=b""):
        self.response, self.sent = response, b""

    def sendall(self, value):
        self.sent += value

    def recv(self, size):
        value = self.response[:min(size, 3)]
        self.response = self.response[len(value):]
        return value

    def close(self):
        pass


def reply(payload, *, xid=7, accepted=0):
    header = b"".join(map(client.uint, (xid, 1, 0, 0, 0, accepted)))
    return header + payload


def frame(data, last=True):
    return client.uint((0x80000000 if last else 0) | len(data)) + data


def test_fragmented_rpc_and_partial_socket_reads(monkeypatch):
    monkeypatch.setattr(client.secrets, "randbits", lambda _: 7)
    data = reply(client.uint(123))
    sock = Socket(frame(data[:11], False) + frame(data[11:]))
    result = client.exchange(sock, 100003, 7, b"fixture")
    assert result.uint() == 123
    result.done()
    marker = struct.unpack("!I", sock.sent[:4])[0]
    assert marker == 0x80000000 | (len(sock.sent) - 4)
    assert struct.unpack("!6I", sock.sent[4:28]) == (7, 0, 2, 100003, 3, 7)


@pytest.mark.parametrize("response", [frame(reply(b"", xid=8)), frame(reply(b"", accepted=1)),
                                    client.uint(0x80010001), frame(b"short"), client.uint(0x80000008) + b"x"])
def test_invalid_rpc_is_never_accepted(monkeypatch, response):
    monkeypatch.setattr(client.secrets, "randbits", lambda _: 7)
    with pytest.raises((RuntimeError, ConnectionError)):
        client.exchange(Socket(response), 100003, 7, b"")


@pytest.mark.parametrize("count, stable", [(8, 2), (7, 2), (8, 0), (8, 1)])
def test_write_requires_complete_file_sync(monkeypatch, count, stable):
    data = client.uint(0) * 3 + client.uint(count) + client.uint(stable) + b"verifier"
    monkeypatch.setattr(client, "exchange", lambda *args: client.Reader(data))
    if (count, stable) == (8, 2):
        client.write(Socket(), b"handle", b"BEFORE!\n")
    else:
        with pytest.raises(RuntimeError, match="FILE_SYNC"):
            client.write(Socket(), b"handle", b"BEFORE!\n")


def test_mount_and_lookup_handle_protocol(monkeypatch):
    root = b"root-handle"
    responses = [client.uint(0) + client.opaque(root) + client.uint(1) + client.uint(1),
                 client.uint(0) + client.opaque(b"file-handle") + client.uint(0) * 2]
    calls = []
    def exchange(sock, program, procedure, arguments):
        calls.append((program, procedure, arguments))
        return client.Reader(responses.pop(0))
    monkeypatch.setattr(client, "exchange", exchange)
    monkeypatch.setattr(client, "connect", lambda _: Socket())
    assert client.file_handle("/fixture/data") == b"file-handle"
    assert calls == [(100005, 1, client.opaque(b"/fixture/data")),
                     (100003, 3, client.opaque(root) + client.opaque(b"payload.bin"))]


@pytest.mark.parametrize("payload", [client.uint(0) + client.opaque(b"") + client.uint(1),
                                   client.uint(0) + client.opaque(b"root") + client.uint(100),
                                   client.uint(0) + client.opaque(b"root") + client.uint(1) + client.uint(0)])
def test_invalid_mount_authentication_or_handle_refused(monkeypatch, payload):
    monkeypatch.setattr(client, "connect", lambda _: Socket())
    monkeypatch.setattr(client, "exchange", lambda *args: client.Reader(payload))
    with pytest.raises(RuntimeError):
        client.file_handle("/fixture/data")


def test_transport_failures_are_not_retried_before_explicit_restoration(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(client, "connect", lambda _: Socket())
    monkeypatch.setattr(client, "file_handle", lambda _: b"handle")
    monkeypatch.setattr(client, "wait", lambda control, phase: events.append(phase))
    monkeypatch.setattr(client, "mark", lambda control, phase: events.append(phase))
    def write(sock, handle, payload):
        events.append(payload)
        if payload in (b"DURING!\n", b"NEWTRY!\n"):
            raise ConnectionResetError("fixture transport unavailable")
    monkeypatch.setattr(client, "write", write)
    report = client.run(tmp_path, "/fixture/data")
    assert events == ["server.ready", b"BEFORE!\n", "client.ready", "server.paused",
                      b"DURING!\n", b"NEWTRY!\n", "client.blocked", "server.restored",
                      b"AFTER!!\n", "client.complete"]
    assert report["automatic_write_retries"] == 0
    assert report["writer_exclusion_verified"] is False


def test_protocol_error_while_paused_is_not_reported_as_denial(tmp_path, monkeypatch):
    marks = []
    monkeypatch.setattr(client, "connect", lambda _: Socket())
    monkeypatch.setattr(client, "file_handle", lambda _: b"handle")
    monkeypatch.setattr(client, "wait", lambda *args: None)
    monkeypatch.setattr(client, "mark", lambda control, phase: marks.append(phase))
    def write(sock, handle, payload):
        if payload != b"BEFORE!\n":
            raise RuntimeError("invalid protocol reply")
    monkeypatch.setattr(client, "write", write)
    with pytest.raises(RuntimeError):
        client.run(tmp_path, "/fixture/data")
    assert marks == ["client.ready"]
