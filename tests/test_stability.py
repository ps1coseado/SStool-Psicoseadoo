"""Compatibilidad con Windows personalizados y estabilidad (sin necesitar Windows)."""
import http.client
import io
import json
import logging
import os
import socket
import ssl
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import diagnostics, launcher, net, paths, webview_runtime
from ui import web_app
from ui.web_server import BrowserServer


class PathsTests(unittest.TestCase):
    def test_data_dir_skips_unwritable_localappdata(self):
        with tempfile.TemporaryDirectory() as good:
            blocked = Path(good) / 'blocked'
            blocked.write_text('a file, so a folder cannot be created below it')
            env = {'LOCALAPPDATA': str(blocked), 'APPDATA': str(Path(good) / 'roaming')}
            with patch.dict('os.environ', env), patch('core.paths.tempfile.gettempdir', return_value=good):
                folder = paths.data_dir()
            self.assertEqual(folder, Path(good) / 'roaming' / paths.APP_FOLDER)

    def test_system_path_is_repaired_only_on_windows(self):
        with patch.object(paths.sys, 'platform', 'linux'):
            self.assertEqual(paths.ensure_system_path(), [])
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'System32' / 'WindowsPowerShell' / 'v1.0').mkdir(parents=True)
            with patch.object(paths.sys, 'platform', 'win32'), \
                    patch.dict('os.environ', {'SystemRoot': root, 'PATH': 'C:\\Tools'}):
                missing = paths.ensure_system_path()
                self.assertIn(str(Path(root) / 'System32' / 'WindowsPowerShell' / 'v1.0'), os.environ['PATH'].split(os.pathsep))
            self.assertTrue(missing)


class NetworkTests(unittest.TestCase):
    def test_certificate_failure_retries_with_bundled_certificates_never_unverified(self):
        error = urllib.error.URLError(ssl.SSLCertVerificationError('CERTIFICATE_VERIFY_FAILED'))
        calls = []

        def fake(request, timeout, context=None):
            calls.append(context)
            if context is None:
                raise error
            return 'ok'

        context = ssl.create_default_context()
        with patch('core.net.urllib.request.urlopen', side_effect=fake), \
                patch('core.net._certifi_context', return_value=context):
            self.assertEqual(net.open_url('request', 5), 'ok')
        self.assertIsNone(calls[0])
        self.assertIs(calls[1], context)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_other_errors_are_not_masked(self):
        with patch('core.net.urllib.request.urlopen', side_effect=urllib.error.URLError('down')), \
                patch('core.net._certifi_context') as certifi:
            with self.assertRaises(urllib.error.URLError):
                net.open_url('request', 5)
            certifi.assert_not_called()

    def test_retry_once_only_for_transient_failures(self):
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionResetError()
            return 'done'

        with patch('core.net.time.sleep'):
            self.assertEqual(net.retry_once(flaky), 'done')
            fatal = MagicMock(side_effect=ValueError('no retry'))
            with self.assertRaises(ValueError):
                net.retry_once(fatal)
        self.assertEqual(fatal.call_count, 1)

    def test_friendly_messages(self):
        self.assertIn('HTTP 404', net.describe_error(urllib.error.HTTPError('u', 404, 'x', {}, None)))
        self.assertIn('fecha', net.describe_error(urllib.error.URLError(ssl.SSLCertVerificationError('CERTIFICATE_VERIFY_FAILED'))))
        self.assertIn('DNS', net.describe_error(urllib.error.URLError(socket.gaierror())))
        self.assertIn('antivirus', net.describe_error(PermissionError()))
        self.assertIn('corto', net.describe_error(http.client.IncompleteRead(b'')))

    def test_download_retries_a_cut_connection_once(self):
        payload = b'MZ' + b'x' * 30

        class Response(io.BytesIO):
            headers = {'Content-Length': str(len(payload))}
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                self.close()

        responses = [ConnectionResetError('cut'), Response(payload)]

        def fake(*_args, **_kwargs):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with tempfile.TemporaryDirectory() as folder, \
                patch('core.net.urllib.request.urlopen', side_effect=fake), \
                patch('core.launcher.time.sleep'):
            path = launcher._download_to_temp('https://example.invalid/t.exe', folder)
            self.assertEqual(Path(path).read_bytes(), payload)

    def test_http_exceptions_do_not_escape_the_launcher(self):
        tool = {'name': 'Broken', 'path': 'Broken.exe', 'url': 'https://example.invalid/Broken.exe'}
        errors = []
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict('os.environ', {'USERPROFILE': folder}), \
                patch('core.launcher._download_tool', side_effect=http.client.IncompleteRead(b'')):
            ok = launcher.launch_tool('orbdiff', tool, on_error=errors.append)
        self.assertFalse(ok)
        self.assertIn('Broken', errors[0])

    def test_tools_folder_falls_back_when_downloads_is_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            blocked = Path(folder) / 'Downloads'
            blocked.write_text('file where a folder is expected')
            launcher._ROOT_CACHE.clear()
            with patch.dict('os.environ', {'USERPROFILE': folder, 'LOCALAPPDATA': str(Path(folder) / 'local')}):
                root = launcher.tools_root_directory()
            launcher._ROOT_CACHE.clear()
            self.assertTrue(root.startswith(str(Path(folder) / 'local')))


class RuntimeTests(unittest.TestCase):
    def test_detection_is_a_noop_outside_windows(self):
        self.assertTrue(webview_runtime.detect())
        self.assertEqual(webview_runtime.ensure_runtime(), 'webview')

    def test_missing_runtime_declined_opens_browser_mode(self):
        with patch.object(webview_runtime, 'detect', return_value=False), \
                patch.object(webview_runtime, '_ask_install', return_value=False):
            self.assertEqual(webview_runtime.ensure_runtime(), 'browser')

    def test_missing_runtime_installed_uses_native_window(self):
        with patch.object(webview_runtime, 'detect', return_value=False), \
                patch.object(webview_runtime, '_ask_install', return_value=True), \
                patch.object(webview_runtime, 'install_runtime', return_value=True):
            self.assertEqual(webview_runtime.ensure_runtime(), 'webview')

    def test_unsigned_bootstrapper_is_never_executed(self):
        class Response(io.BytesIO):
            def __enter__(self):
                return self
            def __exit__(self, *_a):
                self.close()
        data = b'MZ' + b'0' * (webview_runtime.MIN_BOOTSTRAPPER + 10)
        with patch.object(webview_runtime.net, 'open_url', return_value=Response(data)), \
                patch.object(webview_runtime, '_microsoft_signature_valid', return_value=False), \
                patch.object(webview_runtime.subprocess, 'run') as run:
            self.assertFalse(webview_runtime.install_runtime())
            run.assert_not_called()

    def test_portable_runtime_next_to_the_exe_is_detected(self):
        with tempfile.TemporaryDirectory() as base:
            runtime = Path(base) / 'WebView2Runtime' / '120.0'
            runtime.mkdir(parents=True)
            (runtime / 'msedgewebview2.exe').write_bytes(b'MZ')
            fake_main = str(Path(base) / 'main.py')
            with patch.object(webview_runtime, 'is_windows', return_value=True), \
                    patch.object(webview_runtime.sys, 'argv', [fake_main]), \
                    patch.dict('os.environ', {}, clear=False):
                os.environ.pop('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER', None)
                self.assertTrue(webview_runtime.detect())
                self.assertEqual(os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'], str(runtime))
                os.environ.pop('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER', None)


class PageTests(unittest.TestCase):
    def test_wallpaper_is_a_fixed_layer_with_fallback_color(self):
        page = web_app.document()
        self.assertIn('url("background.jpg")', page)
        self.assertIn('position:fixed', page.split('sstool-background')[1])
        self.assertIn('#0b0b0c', page)
        self.assertTrue(Path(web_app.asset_path('background.jpg')).is_file())

    def test_animated_starfield_is_embedded_in_normal_and_safe_mode(self):
        normal = web_app.document()
        safe = web_app.document(safe=True)
        self.assertIn('__sstoolStarfield', normal)
        self.assertIn('__sstoolStarfield', safe)
        self.assertIn('sstool-stars', normal)
        self.assertIn('radial-gradient(ellipse 90% 65% at 50% -12%', normal)
        # Safe mode must add low-effects before the starfield script reads the class.
        self.assertLess(safe.index("classList.add('low-effects')"), safe.index('__sstoolStarfield'))

    def test_safe_mode_skips_intro_and_effects(self):
        self.assertNotIn('finishIntro()}catch', web_app.document())
        safe = web_app.document(safe=True)
        self.assertIn('try{finishIntro()}catch', safe)
        self.assertIn('window.SSToolSafeMode=true', safe)

    def test_intro_has_fast_watchdog_for_missing_codecs(self):
        self.assertIn('setTimeout(finishIntro,10000)', web_app.document())

    def test_prepare_page_copies_wallpaper_next_to_the_page(self):
        with tempfile.TemporaryDirectory() as folder:
            page, background, text = web_app._prepare_page(Path(folder), safe=False)
            self.assertTrue(page.is_file() and background.is_file())
            self.assertEqual(page.parent, background.parent)
            self.assertIn('background.jpg', text)

    def test_failed_previous_start_enables_safe_mode_and_cleans_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            safe, flag = web_app._begin_start(folder, False)
            self.assertFalse(safe)
            (folder / 'WebView2').mkdir()
            safe, flag = web_app._begin_start(folder, False)  # la marca seguia ahi
            self.assertTrue(safe)
            self.assertFalse((folder / 'WebView2').exists())
            web_app._clear_flag(flag)
            safe, _flag = web_app._begin_start(folder, False)
            self.assertFalse(safe)

    def test_native_window_failure_before_load_switches_to_browser(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict('os.environ', {'LOCALAPPDATA': folder}), \
                patch.object(web_app, '_run_webview', side_effect=RuntimeError('no WebView2')), \
                patch.object(web_app, '_run_browser') as browser:
            web_app.run([])
        browser.assert_called_once()

    def test_forced_browser_mode_never_touches_native_window(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict('os.environ', {'LOCALAPPDATA': folder}), \
                patch.object(web_app, '_run_webview') as native, \
                patch.object(web_app, '_run_browser') as browser:
            web_app.run(['--browser'])
        native.assert_not_called()
        browser.assert_called_once()


class BrowserServerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.background = Path(self.folder.name) / 'background.jpg'
        self.background.write_bytes(b'\xff\xd8jpeg')
        self.bridge = web_app.Bridge()
        self.server = BrowserServer(self.bridge, '<!doctype html><html><head></head><body>hi</body></html>', self.background)
        self.thread = threading.Thread(target=self.server._httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server._httpd.shutdown()
        self.server._httpd.server_close()
        self.folder.cleanup()

    def request(self, method, path, body=None, headers=None, host=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=5)
        merged = {'Host': host or f'127.0.0.1:{self.server.port}'}
        merged.update(headers or {})
        connection.request(method, path, body=body, headers=merged)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data, response

    def rpc(self, method, args, token=None):
        body = json.dumps({'m': method, 'a': args})
        headers = {'Content-Type': 'application/json', 'X-SSTool-Token': self.server.token if token is None else token}
        return self.request('POST', '/rpc', body, headers)

    def test_page_requires_token_and_injects_bridge_shim(self):
        self.assertEqual(self.request('GET', '/')[0], 403)
        self.assertEqual(self.request('GET', '/?t=wrong')[0], 403)
        status, data, response = self.request('GET', f'/?t={self.server.token}')
        self.assertEqual(status, 200)
        self.assertIn(b'window.pywebview', data)
        self.assertIn('default-src', response.getheader('Content-Security-Policy'))

    def test_dns_rebinding_host_is_rejected(self):
        self.assertEqual(self.request('GET', f'/?t={self.server.token}', host='evil.example')[0], 403)
        self.assertEqual(self.rpc('ping', [])[0], 200)
        status, _data, _r = self.request('POST', '/rpc', '{}', {'X-SSTool-Token': self.server.token}, host='evil.example')
        self.assertEqual(status, 403)

    def test_rpc_needs_token_and_only_launches_catalogued_tools(self):
        self.assertEqual(self.rpc('ping', [], token='bad')[0], 403)
        status, data, _r = self.rpc('launch', ['C:\\Windows\\System32\\calc.exe'])
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(data)['r']['accepted'])
        self.assertEqual(self.rpc('os_system', ['calc'])[0], 500)

    def test_body_limit_and_bad_json(self):
        headers = {'Content-Type': 'application/json', 'X-SSTool-Token': self.server.token}
        self.assertEqual(self.request('POST', '/rpc', 'x' * 5000, headers)[0], 413)
        self.assertEqual(self.request('POST', '/rpc', 'not json', headers)[0], 400)

    def test_wallpaper_is_served_and_close_stops_the_server(self):
        status, data, _r = self.request('GET', '/background.jpg')
        self.assertEqual((status, data[:2]), (200, b'\xff\xd8'))
        self.assertEqual(self.request('GET', '/secret.txt')[0], 404)
        self.assertEqual(self.rpc('window_control', ['minimize'])[0], 200)
        self.assertFalse(self.server.stop.is_set())
        self.assertEqual(self.rpc('window_control', ['close'])[0], 200)
        self.assertTrue(self.server.stop.wait(2))

    def test_window_controls_without_native_window_do_not_crash(self):
        self.assertFalse(web_app.Bridge().window_control('maximize'))


class DiagnosticsTests(unittest.TestCase):
    def test_log_file_and_hooks_are_installed_once(self):
        old_hook, old_thread_hook = sys.excepthook, threading.excepthook
        logger = diagnostics.get_logger()
        handlers = list(logger.handlers)
        diagnostics._configured = False
        try:
            with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'LOCALAPPDATA': folder}):
                diagnostics.setup_logging()
                logger.error('probe-line')
                for handler in logger.handlers:
                    handler.flush()
                text = (Path(folder) / paths.APP_FOLDER / 'sstool.log').read_text(encoding='utf-8')
                self.assertIn('probe-line', text)
                self.assertIsNot(sys.excepthook, old_hook)
                for handler in list(logger.handlers):
                    handler.close()
                    logger.removeHandler(handler)
                # Windows no deja borrar la carpeta con el log nativo abierto.
                import faulthandler
                faulthandler.disable()
                if diagnostics._fault_file:
                    diagnostics._fault_file.close()
                    diagnostics._fault_file = None
        finally:
            sys.excepthook, threading.excepthook = old_hook, old_thread_hook
            logger.handlers[:] = handlers
            diagnostics._configured = True
            if diagnostics._fault_file:
                import faulthandler
                faulthandler.disable()
                diagnostics._fault_file.close()
                diagnostics._fault_file = None


if __name__ == '__main__':
    unittest.main()
