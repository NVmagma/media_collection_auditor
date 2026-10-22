#!/usr/bin/env python3
"""Private Unix HTTP fixture ONLY; never connects to a real Docker daemon."""
import argparse
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import socket
import socketserver
import time

MARKER = b"DISPOSABLE DOCKER CONTROL FIXTURE ONLY\n"
IDENTITY = "disposable_control_fixture"


class UnixConnection(HTTPConnection):
    def __init__(self, path):
        super().__init__("fixture", timeout=2)
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def request(connection, method, path):
    connection.request(method, path, body=b"" if method == "POST" else None)
    response = connection.getresponse()
    payload = response.read(4097)
    if response.status != 200 or len(payload) > 4096:
        raise RuntimeError("Private fixture response rejected")
    result = json.loads(payload)
    if result.get("fixture") != IDENTITY:
        raise RuntimeError("Private fixture identity required")
    return result


def verify(root):
    if (root / ".disposable_docker_control").read_bytes() != MARKER:
        raise RuntimeError("Private fixture marker required")


def read_count(root):
    value = int((root / "calls").read_text())
    if not 0 <= value <= 2:
        raise RuntimeError("Invalid private fixture count")
    return value


def serve():
    root = Path("/fixture")
    verify(root)
    if read_count(root) != 0:
        raise RuntimeError("New private fixture required")
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def reply(self, status, payload):
            data = json.dumps(payload).encode("ascii")
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != "/fixture/status":
                self.reply(404, {})
                return
            verify(root)
            self.reply(200, {"fixture": IDENTITY, "calls": read_count(root)})

        def do_POST(self):
            if self.path != "/fixture/start" or self.headers.get("Content-Length") != "0":
                self.reply(404, {})
                return
            verify(root)
            count = read_count(root)
            if count >= 2:
                raise RuntimeError("Private fixture request bound exceeded")
            # Fixed counter only: no subprocess, Docker API, media or callback.
            (root / "calls").write_text(str(count + 1))
            self.reply(200, {"fixture": IDENTITY, "calls": count + 1})

        def log_message(self, *args):
            pass
    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
    with Server(str(root / "api.sock"), Handler) as server:
        with (root / "server.ready").open("xb") as output:
            output.write(MARKER)
        server.serve_forever()


def actor():
    commands = Path("/commands")
    verify(commands)
    if any((commands / ("request." + str(index))).exists() for index in (1, 2)):
        raise RuntimeError("New actor refuses preexisting request markers")
    connection = UnixConnection("/run/fixture.sock")
    try:
        # A real Docker daemon cannot satisfy this private identity handshake.
        if request(connection, "GET", "/fixture/status").get("calls") != 0:
            raise RuntimeError("New private fixture required")
        print("actor_connection_ready", flush=True)
        for index in (1, 2):
            for attempt in range(400):
                if (commands / ("request." + str(index))).is_file():
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("Private fixture request timed out")
            verify(commands)
            # Exactly one attempt, on the same established connection. Never
            # retry an uncertain write or reconnect after a transport failure.
            if connection.sock is None:
                raise RuntimeError("Private fixture connection lost")
            result = request(connection, "POST", "/fixture/start")
            if result.get("calls") != index:
                raise RuntimeError("Private fixture sequence changed")
        raise RuntimeError("Paused actor unexpectedly dispatched its second request")
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("serve", "actor", "probe"))
    args = parser.parse_args()
    if args.role == "serve":
        serve()
    elif args.role == "actor":
        actor()
    else:
        verify(Path("/fixture"))
        connection = UnixConnection("/fixture/api.sock")
        try:
            result = request(connection, "GET", "/fixture/status")
            if result.get("calls") != 1:
                raise RuntimeError("Paused fixture call count changed")
            print(json.dumps({"status": "private_api_alive", "fixture_calls": 1,
                              "production_authorized": False}), flush=True)
        finally:
            connection.close()


if __name__ == "__main__":
    main()
