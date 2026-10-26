#!/usr/bin/env python3
"""Disposable read-service/media-write fixture, never a Jellyfin adapter."""
import argparse
import errno
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

MARKER = b"DISPOSABLE CONTAINER WRITER LAB\n"
BEFORE = b"BEFORE!\n"
DENIED = b"DENIED!\n"
PORT = 18765


class Fixture:
    def __init__(self, media, state):
        self.media, self.state = Path(media), Path(state)
        self.verify()

    def verify(self):
        for root in (self.media, self.state):
            if (root / ".disposable_container_writer").read_bytes() != MARKER:
                raise RuntimeError("Disposable container fixture required")

    def read(self):
        self.verify()
        count = int((self.state / "reads").read_text())
        if count < 0 or count >= 1000:
            raise RuntimeError("Invalid fixture read sequence")
        (self.state / "reads").write_text(str(count + 1))
        return {"fixture_only": True, "request_sequence": count + 1,
                "protection": "keep", "media_digest": hashlib.sha256(
                    (self.media / "payload.bin").read_bytes()).hexdigest()}

    def write(self, data):
        self.verify()
        if data not in (BEFORE, DENIED):
            return 400, {"status": "invalid_fixture_request"}
        try:
            (self.media / "payload.bin").write_bytes(data)
        except OSError as exc:
            if exc.errno == errno.EROFS:
                return 409, {"status": "write_denied", "errno": errno.EROFS}
            raise
        return 200, {"status": "fixture_written"}


def serve():
    fixture = Fixture("/media", "/state")
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def send_json(self, status, payload):
            encoded = json.dumps(payload).encode("ascii")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if self.path != "/protection":
                self.send_json(404, {"status": "unknown_fixture_request"})
                return
            try:
                self.send_json(200, fixture.read())
            except (OSError, ValueError, RuntimeError):
                self.send_json(500, {"status": "fixture_read_failed"})

        def do_POST(self):
            if self.path != "/fixture-write" or self.headers.get("Content-Length") != str(len(BEFORE)):
                self.send_json(400, {"status": "invalid_fixture_request"})
                return
            try:
                status, payload = fixture.write(self.rfile.read(len(BEFORE)))
                self.send_json(status, payload)
            except (OSError, RuntimeError):
                self.send_json(500, {"status": "fixture_write_failed"})

        def log_message(self, *args):
            pass
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


def request(path, data=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request("http://127.0.0.1:" + str(PORT) + path, data=data)
    try:
        response = opener.open(req, timeout=0.5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        payload = response.read(8193)
        if len(payload) > 8192:
            raise RuntimeError("Oversized fixture response")
        return response.code, json.loads(payload)


def check(read_only):
    # Only initial GET readiness is retried. Media writes are attempted once.
    for attempt in range(10):
        try:
            status, first = request("/protection")
            break
        except (urllib.error.URLError, OSError):
            if attempt == 9:
                raise
            time.sleep(0.1)
    if status != 200 or first.get("protection") != "keep":
        raise RuntimeError("Fixture protection read unavailable")
    status, written = request("/fixture-write", DENIED if read_only else BEFORE)
    expected = (409, {"status": "write_denied", "errno": errno.EROFS}) if read_only else (
        200, {"status": "fixture_written"})
    if (status, written) != expected:
        raise RuntimeError("Unexpected fixture write outcome")
    status, second = request("/protection")
    if (status != 200 or second.get("protection") != "keep"
            or second.get("request_sequence", -1) <= first["request_sequence"]
            or second.get("media_digest") != hashlib.sha256(BEFORE).hexdigest()):
        raise RuntimeError("Fixture read after write probe failed")
    return {"status": "read_only_media_verified" if read_only else "disposable_writer_verified",
            "fresh_fixture_reads": True, "media_write_attempts": 1,
            "fixture_only": True, "production_authorized": False,
            "production_activation": "disabled", "writer_exclusion_verified": False,
            "restart_inhibition_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("serve", "check-rw", "check-ro"))
    args = parser.parse_args()
    if args.role == "serve":
        serve()
    else:
        print(json.dumps(check(args.role == "check-ro"), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
