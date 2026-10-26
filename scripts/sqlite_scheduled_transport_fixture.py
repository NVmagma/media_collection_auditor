"""Real private-loopback HTTP acceptance; synthetic data/token only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from threading import Thread
import unittest
from unittest.mock import patch

from app.sqlite_scheduled_jellyfin import scheduled_protection_provider
from app.sqlite_scheduled_plan import PlannedMove
from app.sqlite_scheduled_transport import ScheduledJellyfinGET, ScheduledTransportError


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.server.observed.append((self.command, self.path, self.headers.get('X-Emby-Token'),
                                     self.headers.get('Cache-Control')))
        mode = self.server.mode
        if mode == 'redirect':
            self.send_response(302); self.send_header('Location', 'http://127.0.0.1:9/other')
            self.end_headers(); return
        if mode == 'unauthorized':
            self.send_response(401); self.end_headers(); return
        if mode == 'duplicate': data = b'{"key":1,"key":2}'
        elif mode == 'nonfinite': data = b'[NaN]'
        elif mode == 'invalid': data = b'not json'
        elif mode == 'large': data = b' ' * 1000
        elif self.path == '/Users': data = json.dumps([{'Id': 'fixture-user'}]).encode()
        else:
            data = json.dumps({'TotalRecordCount': 1, 'Items': [{'Id': 'fixture-movie', 'Type': 'Movie',
                'Path': '/media/Movies/Movie/file.mkv', 'Tags': self.server.tags,
                'UserData': {'IsFavorite': False, 'Played': False, 'PlayCount': 0}}]}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)


class ScheduledTransportFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.worker = Thread(target=lambda: cls.server.serve_forever(poll_interval=0.01), daemon=True)
        cls.worker.start()
        cls.base_url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.worker.join(timeout=2)

    def setUp(self):
        self.server.mode = 'normal'; self.server.observed = []; self.server.tags = []

    def transport(self, **kwargs):
        return ScheduledJellyfinGET(base_url=self.base_url, token='synthetic-fixture-token', **kwargs)

    def test_real_get_has_token_and_cache_bypass_without_proxy_inheritance(self):
        with patch.dict(os.environ, {'http_proxy': 'http://127.0.0.1:9', 'HTTP_PROXY': 'http://127.0.0.1:9'}):
            self.assertEqual(self.transport()('/Users', None), [{'Id': 'fixture-user'}])
        self.assertEqual(self.server.observed[0], ('GET', '/Users', 'synthetic-fixture-token', 'no-cache'))

    def test_redirect_is_not_followed_or_retried(self):
        self.server.mode = 'redirect'
        with self.assertRaisesRegex(ScheduledTransportError, 'redirect_rejected'):
            self.transport()('/Users', None)
        self.assertEqual(len(self.server.observed), 1)

    def test_unauthorized_response_not_retried_or_echoed(self):
        self.server.mode = 'unauthorized'
        with self.assertRaises(ScheduledTransportError) as error: self.transport()('/Users', None)
        self.assertEqual(str(error.exception), 'http_response_rejected')
        self.assertEqual(len(self.server.observed), 1)

    def test_invalid_duplicate_and_nonfinite_json_fail_closed(self):
        for mode in ('invalid', 'duplicate', 'nonfinite'):
            with self.subTest(mode=mode):
                self.server.mode = mode
                with self.assertRaisesRegex(ScheduledTransportError, 'invalid_json'):
                    self.transport()('/Users', None)

    def test_oversized_body_is_rejected(self):
        self.server.mode = 'large'
        with self.assertRaisesRegex(ScheduledTransportError, 'response_size_exceeded'):
            self.transport(maximum_bytes=20)('/Users', None)

    def test_request_budget_prevents_another_request(self):
        transport = self.transport(maximum_requests=1)
        transport('/Users', None)
        with self.assertRaisesRegex(ScheduledTransportError, 'request_limit_exceeded'):
            transport('/Users', None)
        self.assertEqual(len(self.server.observed), 1)

    def test_mutating_and_ambiguous_routes_are_rejected_before_http(self):
        for path in ('/Items/movie', '//outside/Users', '/Users/u/../Items', '/Users/u?token=x/Items', '/Users/u/Items#x'):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ScheduledTransportError, 'route_rejected'):
                    self.transport()(path, None)
        self.assertEqual(self.server.observed, [])

    def test_unknown_query_is_rejected_before_http(self):
        with self.assertRaisesRegex(ScheduledTransportError, 'query_rejected'):
            self.transport()('/Users', {'api_key': 'forbidden'})
        self.assertEqual(self.server.observed, [])

    def test_representation_omits_credentials_and_url(self):
        rendered = repr(self.transport())
        self.assertNotIn('synthetic-fixture-token', rendered); self.assertNotIn(self.base_url, rendered)

    def test_real_http_collector_refetch_sees_new_protection(self):
        move = PlannedMove('Movies', 'Movie', 'Waiting', 'Holding', 'hold', '2024-01-01', 7)
        provider = scheduled_protection_provider(fetch=self.transport(), bindings={'Movie': ('Movie', 'Movie')})
        self.assertFalse(provider(move).signals['protected'])
        self.server.tags = ['keep-forever']
        second = provider(move)
        self.assertTrue(second.available and second.signals['protected'] and second.signals['keep_all'])
        self.assertEqual(len(self.server.observed), 4)

    def test_invalid_connection_config_is_rejected_without_requests(self):
        for url in ('http://user:password@host', 'file:///etc/passwd', 'http://host/?key=secret',
                    'http://host/#fragment', 'http://host:bad', 'http://host\n'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError): ScheduledJellyfinGET(base_url=url, token='fixture')
        self.assertEqual(self.server.observed, [])


if __name__ == '__main__':
    unittest.main()
