"""Modo navegador: misma interfaz sin WebView2, servida solo en 127.0.0.1.

Se usa cuando el runtime WebView2 no existe (tipico en Windows personalizados). Solo
admite las mismas cuatro llamadas que el puente de pywebview y el Bridge sigue
limitando las acciones a las herramientas del catalogo.

Defensas: escucha solo en loopback, puerto aleatorio, token por sesion en cabecera
personalizada (obliga a preflight CORS, que no se concede), comprobacion de Host
contra DNS-rebinding, cuerpo maximo de 4 KB y CSP sin recursos externos.
"""
import hmac
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.diagnostics import get_logger

MAX_BODY = 4096
FIRST_LOAD_GRACE = 180   # segundos para que el navegador cargue la primera vez
IDLE_TIMEOUT = 180       # sin latidos (pestana cerrada) -> la app termina
HEARTBEAT_MS = 15000

CSP = ("default-src 'none'; img-src 'self' data:; media-src data: 'self'; "
       "style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

SHIM = """<script>(()=>{const T=%TOKEN%;
async function rpc(m,a){const r=await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json','X-SSTool-Token':T},body:JSON.stringify({m,a})});if(!r.ok)throw new Error('HTTP '+r.status);return (await r.json()).r}
function fs(a){if(a==='fullscreen'){document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen().catch(()=>{});return true}
if(a==='exit-fullscreen'){if(document.fullscreenElement)document.exitFullscreen();return true}return null}
window.pywebview={api:{launch:i=>rpc('launch',[i]),poll_events:()=>rpc('poll_events',[]),open_link:t=>rpc('open_link',[t]),
window_control:async a=>{const h=fs(a);if(h!==null)return h;const r=await rpc('window_control',[a]);
if(a==='close'){try{window.close()}catch(e){}document.body.textContent='SSTool+ closed. You can close this tab.'}return r}}};
document.documentElement.classList.add('browser-mode');
setInterval(()=>rpc('ping',[]).catch(()=>{}),%BEAT%);})();</script>
<style>.browser-mode [data-window=minimize],.browser-mode [data-window=maximize]{display:none}</style>"""


class BrowserServer:
    def __init__(self, bridge, page_html, background_path=None):
        self.bridge = bridge
        self.token = secrets.token_urlsafe(24)
        self.page_html = page_html
        self.background = Path(background_path) if background_path else None
        self.stop = threading.Event()
        self.last_seen = time.monotonic()
        self.loaded = False
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def page(self):
        shim = SHIM.replace("%TOKEN%", json.dumps(self.token)).replace("%BEAT%", str(HEARTBEAT_MS))
        return self.page_html.replace("<head>", "<head>" + shim, 1).encode("utf-8")

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "SSToolLocal"
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # sin ruido en consola/log
                pass

            def _send(self, status, body=b"", content_type="text/plain; charset=utf-8", extra=None):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                if body and self.command != "HEAD":
                    self.wfile.write(body)

            def _host_ok(self):
                return self.headers.get("Host", "") in (f"127.0.0.1:{server.port}", f"localhost:{server.port}")

            def do_GET(self):
                if not self._host_ok():
                    return self._send(403, b"forbidden")
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    token = (parse_qs(parsed.query).get("t") or [""])[0]
                    if not hmac.compare_digest(token, server.token):
                        return self._send(403, b"forbidden")
                    server.loaded = True
                    server.last_seen = time.monotonic()
                    return self._send(200, server.page(), "text/html; charset=utf-8",
                                      {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY"})
                if parsed.path == "/background.jpg" and server.background and server.background.is_file():
                    try:
                        return self._send(200, server.background.read_bytes(), "image/jpeg")
                    except OSError:
                        return self._send(404, b"not found")
                return self._send(404, b"not found")

            do_HEAD = do_GET

            def do_POST(self):
                if self.path != "/rpc" or not self._host_ok():
                    return self._send(403, b"forbidden")
                token = self.headers.get("X-SSTool-Token", "")
                if not hmac.compare_digest(token, server.token):
                    return self._send(403, b"forbidden")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if not 0 < length <= MAX_BODY:
                    return self._send(413, b"bad length")
                try:
                    request = json.loads(self.rfile.read(length).decode("utf-8"))
                    method, args = request["m"], request.get("a", [])
                    if not isinstance(method, str) or not isinstance(args, list):
                        raise ValueError
                except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                    return self._send(400, b"bad request")
                server.last_seen = time.monotonic()
                try:
                    result = server.dispatch(method, args)
                except Exception:  # noqa: BLE001
                    get_logger().error("RPC %s failed", method, exc_info=True)
                    return self._send(500, b"error")
                self._send(200, json.dumps({"r": result}).encode("utf-8"), "application/json")

        return Handler

    def dispatch(self, method, args):
        if method == "ping":
            return True
        if method == "poll_events":
            return self.bridge.poll_events()
        if method == "launch" and len(args) == 1:
            return self.bridge.launch(args[0])
        if method == "open_link" and len(args) == 1:
            return self.bridge.open_link(args[0])
        if method == "window_control" and args == ["close"]:
            threading.Timer(0.3, self.stop.set).start()
            return True
        if method == "window_control":
            return False
        raise ValueError("unknown method")

    def _watchdog(self):
        started = time.monotonic()
        while not self.stop.wait(5):
            now = time.monotonic()
            if not self.loaded:
                if now - started > FIRST_LOAD_GRACE:
                    get_logger().warning("El navegador nunca cargo la interfaz; se cierra")
                    break
            elif now - self.last_seen > IDLE_TIMEOUT:
                get_logger().info("Pestana cerrada (sin latidos); se cierra")
                break
        self.stop.set()

    def run(self, open_browser=True, on_open_failed=None):
        thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.5},
                                  daemon=True, name="sstool-http")
        thread.start()
        threading.Thread(target=self._watchdog, daemon=True, name="sstool-watchdog").start()
        get_logger().info("Modo navegador en 127.0.0.1:%s", self.port)
        if open_browser:
            opened = False
            try:
                opened = webbrowser.open(self.url)
            except Exception:  # noqa: BLE001
                get_logger().error("webbrowser.open fallo", exc_info=True)
            if not opened and on_open_failed:
                on_open_failed(self.url)
        self.stop.wait()
        self._httpd.shutdown()
        self._httpd.server_close()
