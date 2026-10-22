#!/usr/bin/env python3
"""Bounded loopback-only NFSv3 wire client for the isolated namespace lab.

No kernel client mount/LOCALIO, credentials, configurable network destination,
retry of uncertain writes, deletion, service controls or production permit.
Protocol layout: RFC 1813 and RFC 5531. Fixed eight-byte fixture writes only.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import struct
import time


def uint(value):
    return struct.pack("!I", value)


def opaque(value):
    return uint(len(value)) + value + b"\0" * (-len(value) % 4)


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, size):
        if size < 0 or size > len(self.data) - self.offset:
            raise RuntimeError("Truncated RPC response")
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        return value

    def uint(self):
        return struct.unpack("!I", self.take(4))[0]

    def opaque(self, maximum):
        size = self.uint()
        if size > maximum:
            raise RuntimeError("Oversized RPC field")
        value = self.take(size)
        if self.take(-size % 4) != b"\0" * (-size % 4):
            raise RuntimeError("Invalid XDR padding")
        return value

    def optional(self, size):
        present = self.uint()
        if present not in (0, 1):
            raise RuntimeError("Invalid XDR boolean")
        if present:
            self.take(size)

    def done(self):
        if self.offset != len(self.data):
            raise RuntimeError("Unexpected RPC response fields")


def exact(sock, size):
    output = bytearray()
    while len(output) < size:
        chunk = sock.recv(size - len(output))
        if not chunk:
            raise ConnectionError("RPC connection closed")
        output.extend(chunk)
    return bytes(output)


def exchange(sock, program, procedure, arguments):
    xid = secrets.randbits(32)
    auth = uint(0) + opaque(b"auditor-fixture") + uint(0) * 3
    call = b"".join(map(uint, (xid, 0, 2, program, 3, procedure)))
    call += uint(1) + opaque(auth) + uint(0) + uint(0) + arguments
    sock.sendall(uint(0x80000000 | len(call)) + call)
    response = bytearray()
    for _ in range(16):
        marker = struct.unpack("!I", exact(sock, 4))[0]
        size = marker & 0x7fffffff
        if size > 65536 - len(response):
            raise RuntimeError("Oversized RPC record")
        response.extend(exact(sock, size))
        if marker & 0x80000000:
            break
    else:
        raise RuntimeError("Too many RPC fragments")
    result = Reader(bytes(response))
    if (result.uint(), result.uint(), result.uint()) != (xid, 1, 0):
        raise RuntimeError("RPC reply identity/acceptance mismatch")
    result.uint()  # Verifier flavor; bounded opaque verifier follows.
    result.opaque(400)
    if result.uint() != 0:
        raise RuntimeError("RPC request not accepted")
    return result


def connect(port):
    # Host and protocol ports are fixed. The harness supplies an isolated netns.
    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
    sock.settimeout(2)
    return sock


def file_handle(export):
    with closing(connect(20048)) as sock:
        result = exchange(sock, 100005, 1, opaque(export.encode("ascii")))
        if result.uint() != 0:
            raise RuntimeError("Fixture export mount refused")
        root = result.opaque(64)
        count = result.uint()
        if not root or not 1 <= count <= 16:
            raise RuntimeError("Invalid mount handle/authentication")
        if 1 not in [result.uint() for _ in range(count)]:
            raise RuntimeError("Fixture AUTH_SYS unavailable")
        result.done()
    with closing(connect(2049)) as sock:
        result = exchange(sock, 100003, 3, opaque(root) + opaque(b"payload.bin"))
        if result.uint() != 0:
            raise RuntimeError("Fixture lookup failed")
        handle = result.opaque(64)
        if not handle:
            raise RuntimeError("Empty fixture handle")
        result.optional(84)
        result.optional(84)
        result.done()
        return handle


def write(sock, handle, payload):
    if payload not in (b"BEFORE!\n", b"DURING!\n", b"NEWTRY!\n", b"AFTER!!\n", b"CRASH!!\n", b"GUARD!!\n"):
        raise ValueError("Fixed disposable payload required")
    arguments = opaque(handle) + struct.pack("!QII", 0, 8, 2) + opaque(payload)
    result = exchange(sock, 100003, 7, arguments)
    if result.uint() != 0:
        raise RuntimeError("NFS fixture write returned an error")
    result.optional(24)  # pre-op weak cache consistency
    result.optional(84)  # post-op attributes
    if (result.uint(), result.uint()) != (8, 2):
        raise RuntimeError("Fixture write was not complete FILE_SYNC")
    result.take(8)  # write verifier
    result.done()


def wait(control, phase):
    deadline = time.monotonic() + 30
    while not (control / phase).is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("Fixture phase timed out: " + phase)
        time.sleep(0.05)


def mark(control, phase):
    with (control / phase).open("xb") as output:
        output.write(b"FIXTURE ONLY\n")


def prepare_pending_journal(control):
    from app.sqlite_disposable_maintenance_journal import (
        create_disposable_journal, advance_disposable_journal)
    root = control / "maintenance-journal"
    create_disposable_journal(root)
    advance_disposable_journal(root, expected_revision=0, phase="fence_requested")


def pending_journal(control):
    from app.sqlite_disposable_maintenance_journal import inspect_disposable_journal
    report = inspect_disposable_journal(control / "maintenance-journal")
    if report["phase"] != "fence_requested" or report["revision"] != 1:
        raise RuntimeError("Crash journal no longer has the unresolved request")
    return report["phase"]


def run(control, export, scenario="restore"):
    if scenario not in ("restore", "controller-crash", "restart-guard"):
        raise ValueError("Unknown disposable scenario")
    wait(control, "server.ready")
    handle = file_handle(export)
    with closing(connect(2049)) as old:
        write(old, handle, b"BEFORE!\n")
        if scenario != "restore":
            # Committed before client.ready allows the pause worker to act.
            # No completion is inferred from observed pause or matching bytes.
            prepare_pending_journal(control)
        mark(control, "client.ready")
        wait(control, "server.paused")
        try:
            write(old, handle, b"DURING!\n")
        except OSError:
            pass  # Uncertain transport outcome, not proof of permanent denial.
        else:
            raise RuntimeError("Old RPC connection completed a write while paused")
    try:
        with closing(connect(2049)) as fresh:
            write(fresh, handle, b"NEWTRY!\n")
    except OSError:
        pass
    else:
        raise RuntimeError("New RPC connection completed a write while paused")
    mark(control, "client.blocked")
    if scenario != "restore":
        wait(control, "server.controller-dead")
        try:
            with closing(connect(2049)) as fresh:
                write(fresh, handle, b"CRASH!!\n")
        except OSError:
            pass
        else:
            raise RuntimeError("Write completed after pause-controller death")
        phase = pending_journal(control)
        mark(control, "client.after-death-blocked")
        if scenario == "restart-guard":
            wait(control, "server.restart-attempts-blocked")
            try:
                with closing(connect(2049)) as fresh:
                    write(fresh, handle, b"GUARD!!\n")
            except OSError:
                pass
            else:
                raise RuntimeError("Write completed after guarded restart attempts")
            phase = pending_journal(control)
            mark(control, "client.restart-probes-complete")
        mark(control, "client.complete")
        return {"status": ("fixture_restart_entrypoints_complete" if scenario == "restart-guard"
                           else "fixture_controller_crash_complete"),
                "pending_phase": phase, "automatic_write_retries": 0,
                "automatic_restoration": False, "production_authorized": False,
                "writer_exclusion_verified": False, "production_activation": "disabled",
                "restart_inhibition_verified": False}
    wait(control, "server.restored")
    # Fresh mount/lookup and explicit new write; never replay DURING or old calls.
    with closing(connect(2049)) as fresh:
        write(fresh, file_handle(export), b"AFTER!!\n")
    mark(control, "client.complete")
    return {"status": "fixture_rpc_complete", "production_authorized": False,
            "writer_exclusion_verified": False, "production_activation": "disabled",
            "paused_requests": "transport_unavailable_outcome_uncertain",
            "automatic_write_retries": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", required=True)
    parser.add_argument("--export", required=True)
    parser.add_argument("--host-netns", required=True)
    parser.add_argument("--scenario", choices=("restore", "controller-crash", "restart-guard"), default="restore")
    args = parser.parse_args()
    control = Path(args.control)
    try:
        if control != Path("/control") or not control.is_dir():
            raise ValueError("Container fixture control directory required")
        if ((control / ".disposable_nfs_rpc").read_bytes() != b"DISPOSABLE NFS RPC LAB\n"
                or os.readlink("/proc/self/ns/net") == args.host_netns):
            raise RuntimeError("Isolated fixture namespace required")
        report = run(control, args.export, args.scenario)
    except (OSError, RuntimeError, ValueError, UnicodeError, struct.error, sqlite3.Error) as exc:
        report = {"status": "blocked", "reason": type(exc).__name__,
                  "production_authorized": False, "writer_exclusion_verified": False}
        print(str(exc), flush=True)
        print(json.dumps(report), flush=True)
        return 2
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
