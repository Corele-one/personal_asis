import contextlib
from http.client import HTTPConnection
from http.server import HTTPServer
import io
import threading
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import Mock, patch

from personal_asis import folo_login
from personal_asis.reading_sources import SourceError


class FoloLoginTests(unittest.TestCase):
    def test_exchange_cookie_and_session_validation(self):
        transport = Mock(side_effect=[
            (200, ['__Secure-better-auth.session_token=session-secret%2Bsignature; Path=/; Secure'], {}),
            (200, [], {'user': {'id': 'synthetic'}, 'session': {'id': 'synthetic'}}),
        ])
        self.assertEqual(folo_login.exchange('one-time-secret', transport), 'session-secret+signature')
        self.assertEqual(transport.call_args_list[1].kwargs, {'token': 'session-secret+signature'})

    def test_404_fallback_and_failed_session_are_sanitized(self):
        transport = Mock(side_effect=[(404, [], {}),
            (200, [], {'session': {'token': 'private-session'}}),
            (401, [], {'message': 'private-session'})])
        with self.assertRaisesRegex(SourceError, '^folo_login_session_rejected$'):
            folo_login.exchange('one-time-secret', transport)
        self.assertEqual(transport.call_args_list[1].args, ('verify',))

    def test_missing_or_unsafe_session_rejected(self):
        for value in (None, '', 'secret\r\nInjected: yes', 'secret;another=credential'):
            with self.assertRaises(SourceError):
                folo_login.exchange('one-time-secret', Mock(return_value=(200, [], {'session': {'token': value}})))

    def test_callback_checks_nonce_host_and_suppresses_secret_logs(self):
        state = {'nonce': 'synthetic-state'}
        output = io.StringIO()
        with HTTPServer(('127.0.0.1', 0), folo_login.callback_handler(state)) as server:
            def get(query):
                thread = threading.Thread(target=server.handle_request)
                thread.start()
                client = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                client.request('GET', '/callback?' + urlencode(query))
                response = client.getresponse()
                status, body = response.status, response.read()
                client.close()
                thread.join(timeout=3)
                return status, body
            with contextlib.redirect_stderr(output):
                self.assertEqual(get({'state': 'wrong', 'token': 'callback-secret'})[0], 400)
                self.assertNotIn('token', state)
                status, body = get({'state': state['nonce'], 'token': 'callback-secret'})
                self.assertEqual(status, 200)
                self.assertNotIn(b'callback-secret', body)
                self.assertEqual(get({'state': state['nonce'], 'token': 'replacement-secret'})[0], 400)
        self.assertEqual(state['token'], 'callback-secret')
        self.assertEqual(output.getvalue(), '')

    def test_login_saves_verified_session_without_plaintext_file(self):
        store, notices = Mock(), []
        workers = []
        def browser(url):
            callback = urlsplit(parse_qs(urlsplit(url).query)['cli_callback'][0])
            def send():
                client = HTTPConnection(callback.hostname, callback.port, timeout=3)
                client.request('GET', callback.path + '?' + callback.query + '&token=callback-secret')
                client.getresponse().read()
                client.close()
            worker = threading.Thread(target=send)
            worker.start()
            workers.append(worker)
        with patch.object(folo_login, 'exchange', return_value='verified-secret'), \
                patch('builtins.open', side_effect=AssertionError('no plaintext persistence')):
            result = folo_login.login(store=store, notify=notices.append, browser=browser)
        for worker in workers:
            worker.join(timeout=3)
        store.set.assert_called_once_with('verified-secret')
        self.assertTrue(result['session_verified'])
        self.assertNotIn('callback-secret', str(notices) + str(result))
        self.assertNotIn('verified-secret', str(notices) + str(result))

    def test_http_redirect_is_denied_and_remote_error_not_exposed(self):
        with patch.object(folo_login, 'build_opener') as opener:
            opener.return_value.open.side_effect = RuntimeError('token=private-secret')
            with self.assertRaisesRegex(SourceError, '^folo_login_network_or_response_error$'):
                folo_login.request('apply', body={'token': 'private-secret'})
            self.assertIsInstance(opener.call_args.args[0], folo_login.NoRedirect)
            req = opener.return_value.open.call_args.args[0]
            self.assertEqual(req.get_header('User-agent'), 'PersonalAsis/1.0 (Folo browser login)')


if __name__ == '__main__':
    unittest.main()
