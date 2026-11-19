"""Local HTML frontend; the browser can dispatch only catalogued tools."""
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from core import webview_runtime
from core.data import CATEGORIES
from core.diagnostics import get_logger, setup_logging
from core.i18n import category_label, tool_description
from core import launcher as _launcher
from core.launcher import launch_tool
from core import workspace
from core.tool_info import APP_VERSION, AUTHOR_GITHUB, UPDATE_REPO, compare_versions, to_english, tool_info
from core.paths import data_dir
from core.windows_shell import asset_path

BACKGROUND_FILE = 'background.jpg'
# Capa fija (no se repinta al hacer scroll) con un cielo rojo profundo. El canvas
# animado de starfield.js se dibuja encima de este degradado; la imagen queda como
# textura muy tenue para que el fondo no dependa solo de JavaScript.
# Ajusta --bg-dim (0 = sin oscurecer) si quieres más o menos textura.
BACKGROUND_CSS = ('<style id="sstool-background">:root{{--bg-dim:.985}}html{{background:#0b0b0c}}'
                  'body{{background:transparent}}'
                  'body::before{{content:"";position:fixed;top:0;right:0;bottom:0;left:0;z-index:-2;pointer-events:none;'
                  'background:'
                  'radial-gradient(ellipse 90% 65% at 50% -12%,rgba(255,52,86,.20),transparent 62%),'
                  'radial-gradient(ellipse 70% 55% at 88% 82%,rgba(142,0,42,.28),transparent 68%),'
                  'radial-gradient(ellipse 65% 50% at 8% 70%,rgba(96,0,28,.30),transparent 70%),'
                  'linear-gradient(rgba(6,2,4,var(--bg-dim)),rgba(6,2,4,var(--bg-dim))),'
                  'url("{url}") center 30%/cover no-repeat #0b0b0c}}'
                  '</style>')


CATEGORY_PAGES = {'nirsoft_utilities': 'https://www.nirsoft.net/'}


def _info(category_id, tool):
    info = tool_info(tool)
    if category_id in CATEGORY_PAGES:
        info['page'] = CATEGORY_PAGES[category_id]
    return info


def catalogue():
    return [dict(id=c['id'], labels={l: category_label(c, l) for l in ('en', 'es')},
                 tools=[dict(id=t.get("id", f"{c['id']}:{i}"), name=t['name'], info=_info(c['id'], t),
                             descriptions={l: tool_description(t, l) for l in ('en', 'es')})
                        for i, t in enumerate(c['tools'])]) for c in CATEGORIES]


def document(background=BACKGROUND_FILE, safe=False):
    """HTML final. ``background`` es una URL relativa o data: URI; ``safe`` desactiva efectos/intro."""
    page = Path(asset_path('interface-template.html')).read_text(encoding='utf-8')
    data = json.dumps(catalogue(), ensure_ascii=True).replace('<', '\\u003c')
    page = re.sub(r"const catalogue=.*?(?=const categoryImages)", lambda _: 'const catalogue=' + data + ';\n', page, count=1, flags=re.S)
    page = page.replace('PsicoseadoSSTool', 'SSTool+')
    page = page.replace('APP_VERSION_PLACEHOLDER', APP_VERSION)
    motion = Path(asset_path('motion.js')).read_text(encoding='utf-8')
    style = '<style>.mouse-trail{position:fixed;left:0;top:0;width:90px;height:20px;border-radius:50%;pointer-events:none;z-index:65;background:radial-gradient(ellipse,#ffffff40,transparent 70%);filter:blur(6px);opacity:0;transform-origin:center}.tab,.card,.controls button,.search-link{transition:background-color .18s,border-color .18s,color .18s}.titlebar{cursor:grab}.titlebar button{cursor:pointer}.title-brand{flex:1;height:100%;display:flex;flex-direction:column;justify-content:center}.title-brand span{pointer-events:none}</style>'
    wallpaper = BACKGROUND_CSS.format(url=str(background).replace('"', '%22').replace('\\', '/'))
    stars = Path(asset_path('starfield.js')).read_text(encoding='utf-8')
    tail = '<script>' + motion + '</script>'
    if safe:
        # Modo seguro tras un arranque fallido: sin video de intro ni efectos pesados.
        tail += "<script>window.SSToolSafeMode=true;document.documentElement.classList.add('low-effects');try{applyMotionMode()}catch(e){}try{finishIntro()}catch(e){}</script>"
    # El starfield se carga al final: pinta estrellas incluso en modo seguro (sin movimiento).
    tail += '<script>' + stars + '</script>'
    return page.replace('</head>', style + wallpaper + '</head>').replace('</body>', tail + '</body>')


class Bridge:
    def __init__(self):
        self._window = None
        self._lock = threading.Lock()
        self._busy = set()
        self._until = {}
        self._slots = threading.Semaphore(2)
        self._events = {}
        self._event_lock = threading.Lock()
        self._tools = {t.get("id", f"{c['id']}:{i}"): (t.get("storage_category", c['id']), t) for c in CATEGORIES for i, t in enumerate(c['tools'])}
        self._infos = {t.get('id', f"{c['id']}:{i}"): _info(c['id'], t) for c in CATEGORIES for i, t in enumerate(c['tools'])}
        self._maximized = False
        self._fullscreen = False
        self._lang = 'en'

    def set_language(self, lang):
        self._lang = 'es' if lang == 'es' else 'en'
        return self._lang

    def _msg(self, en, es):
        return es if self._lang == 'es' else en

    def _emit(self, payload):
        if payload.get('kind') == 'status' and self._lang == 'en':
            payload = dict(payload, message=to_english(payload['message']))
        # Workers must never wait for the renderer (especially while minimized).
        # Coalesce progress: memory stays bounded even if the UI stops polling.
        with self._event_lock:
            key = (payload['id'], payload['kind'])
            self._events.pop(key, None)
            self._events[key] = payload

    def poll_events(self):
        with self._event_lock:
            events = list(self._events.values())
            self._events.clear()
        return events

    def launch(self, tool_id):
        if not isinstance(tool_id, str) or tool_id not in self._tools:
            return {'accepted': False, 'error': 'Unknown tool'}
        with self._lock:
            if len(self._busy) >= 2:
                return {'accepted': False, 'error': 'Two tools are already opening. Please wait.'}
            if tool_id in self._busy or time.monotonic() < self._until.get(tool_id, 0):
                return {'accepted': False, 'error': 'Please wait'}
            self._busy.add(tool_id)
            self._until[tool_id] = time.monotonic() + 5
        try:
            threading.Thread(target=self._run, args=(tool_id,), daemon=True).start()
        except Exception:
            with self._lock:
                self._busy.discard(tool_id)
                self._until.pop(tool_id, None)
            return {'accepted': False, 'error': 'Unable to start the tool. Please retry.'}
        return {'accepted': True}

    def _run(self, tool_id):
        cid, tool = self._tools[tool_id]
        last = [0.0]
        ok = False
        def status(message):
            self._emit(dict(kind='status', id=tool_id, message=str(message)))
        def progress(done, total):
            now = time.monotonic()
            if now - last[0] < .08 and done != total:
                return
            last[0] = now
            self._emit(dict(kind='progress', id=tool_id, name=tool['name'],
                            downloaded_bytes=done, total_bytes=total,
                            percent=min(100, done * 100 / total) if total else None))
        try:
            with self._slots:
                ok = launch_tool(cid, tool, on_missing=status, on_error=status,
                                 on_status=status, on_progress=progress)
                if ok:
                    workspace.record_source(cid, tool)
        except Exception as exc:
            status(str(exc))
            ok = False
        finally:
            with self._lock:
                self._busy.discard(tool_id)
            self._emit(dict(kind='done', id=tool_id, ok=ok))

    def tool_action(self, tool_id, action):
        """Acciones del menu contextual. Solo opera sobre herramientas del catalogo."""
        if not isinstance(tool_id, str) or tool_id not in self._tools:
            return {'ok': False, 'error': self._msg('Unknown tool', 'Herramienta desconocida')}
        cid, tool = self._tools[tool_id]
        info = self._infos[tool_id]
        if action == 'page':
            if not info['page']:
                return {'ok': False, 'error': self._msg('No official page for this tool', 'Esta herramienta no tiene página oficial')}
            return {'ok': bool(webbrowser.open_new_tab(info['page']))}
        if action == 'link':
            if not info['link']:
                return {'ok': False, 'error': self._msg('No download link for this tool', 'Esta herramienta no tiene enlace de descarga')}
            return {'ok': True, 'text': info['link']}
        if action == 'copy':  # respaldo si el portapapeles del WebView no esta disponible
            if not info['link'] or sys.platform != 'win32':
                return {'ok': False}
            try:
                import subprocess
                subprocess.run(['clip'], input=info['link'].encode('utf-8'), check=True, timeout=5,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                return {'ok': True}
            except Exception:  # noqa: BLE001
                return {'ok': False}
        if action not in ('downloads', 'download'):
            return {'ok': False, 'error': 'Unknown action'}
        if not (tool.get('url') or tool.get('mediafire_page')) or tool.get('embedded_script') is not None:
            return {'ok': False, 'error': self._msg('Nothing to download for this tool', 'No hay nada que descargar para esta herramienta')}
        with self._lock:
            if tool_id in self._busy:
                return {'ok': False, 'error': self._msg('Please wait', 'Espera un momento')}
            self._busy.add(tool_id)
        threading.Thread(target=self._download_only, args=(tool_id, action), daemon=True).start()
        return {'ok': True}

    def _download_only(self, tool_id, action):
        cid, tool = self._tools[tool_id]
        name, ok = tool['name'], False
        last = [0.0]

        def progress(done, total):
            now = time.monotonic()
            if now - last[0] < .08 and done != total:
                return
            last[0] = now
            self._emit(dict(kind='progress', id=tool_id, name=name, downloaded_bytes=done, total_bytes=total,
                            percent=min(100, done * 100 / total) if total else None))
        try:
            with self._slots:
                self._emit(dict(kind='status', id=tool_id, message=self._msg(f'Downloading {name}...', f'Descargando {name}...')))
                if action == 'download':
                    path = _launcher.resolve_tool_path(cid, tool)
                    _launcher._download_tool(cid, tool, path, on_progress=progress)
                    workspace.record_source(cid, tool)
                    where = os.path.dirname(path)
                else:
                    url = _launcher._resolve_download_url(tool)
                    folder = _launcher.downloads_directory()
                    name_from_url = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path)) or tool.get('path') or name
                    temp = _launcher._download_to_temp(url, folder, None if tool.get('archive') else tool.get('sha256'), progress)
                    target, stem, n = os.path.join(folder, name_from_url), os.path.splitext(name_from_url)[0], 1
                    while os.path.exists(target):
                        target = os.path.join(folder, f'{stem} ({n}){os.path.splitext(name_from_url)[1]}')
                        n += 1
                    os.replace(temp, target)
                    where = target
            ok = True
            self._emit(dict(kind='status', id=tool_id, message=self._msg(f'{name} saved to: {where}', f'{name} guardado en: {where}')))
        except Exception as exc:  # noqa: BLE001
            get_logger().error('Descarga manual fallida: %s', name, exc_info=True)
            detail = str(exc) if isinstance(exc, _launcher.ToolDownloadError) else _launcher.net.describe_error(exc)
            self._emit(dict(kind='status', id=tool_id, message=self._msg(f'Could not download {name}:\n', f'No se pudo descargar {name}:\n') + detail))
        finally:
            with self._lock:
                self._busy.discard(tool_id)
            self._emit(dict(kind='done', id=tool_id, ok=ok))

    def app_info(self):
        """Version instalada y, si hay red, la ultima release publicada."""
        out = {'version': APP_VERSION, 'latest': None, 'up_to_date': None}
        try:
            req = urllib.request.Request(f'https://api.github.com/repos/{UPDATE_REPO}/releases/latest',
                                         headers={'User-Agent': 'SSTool+', 'Accept': 'application/vnd.github+json'})
            with _launcher.net.open_url(req, 6) as r:
                tag = json.loads(r.read(200000).decode('utf-8')).get('tag_name')
            if tag:
                out['latest'] = tag
                out['up_to_date'] = not compare_versions(APP_VERSION, tag)
        except Exception:  # noqa: BLE001 - sin red / sin releases: se muestra "no se pudo comprobar"
            get_logger().info('No se pudo comprobar la ultima version', exc_info=True)
        return out

    def window_control(self, action):
        if self._window is None:
            return False
        if action == 'minimize':
            self._window.minimize()
        elif action == 'maximize':
            if self._fullscreen:
                self._window.toggle_fullscreen()
                self._fullscreen = False
                return True
            if self._maximized:
                self._window.restore()
            else:
                self._window.maximize()
            self._maximized = not self._maximized
        elif action == 'fullscreen':
            self._window.toggle_fullscreen()
            self._fullscreen = not self._fullscreen
        elif action == 'exit-fullscreen':
            if self._fullscreen:
                self._window.toggle_fullscreen()
                self._fullscreen = False
        elif action == 'close':
            self._window.destroy()
        else:
            return False
        return True

    def open_link(self, target):
        urls = {'github': AUTHOR_GITHUB, 'releases': f'https://github.com/{UPDATE_REPO}', 'discord': 'https://discord.gg/bhD5sheFf4'}
        if target not in urls:
            return False
        return webbrowser.open_new_tab(urls[target])


def _write_atomic(path, text):
    """Escribe y reemplaza de golpe: un cierre brusco nunca deja la pagina a medias."""
    temp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    try:
        temp.write_text(text, encoding='utf-8')
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def _copy_if_changed(source, target):
    try:
        if target.exists() and target.stat().st_size == source.stat().st_size:
            return True
        shutil.copyfile(source, target)
        return True
    except OSError:
        get_logger().warning('No se pudo copiar el fondo a %s', target, exc_info=True)
        return False


def _prepare_page(folder, safe):
    """Deja interface.html y background.jpg juntos en una carpeta escribible."""
    background = folder / BACKGROUND_FILE
    _copy_if_changed(Path(asset_path(BACKGROUND_FILE)), background)
    page = folder / 'interface.html'
    html_text = document(safe=safe)
    try:
        _write_atomic(page, html_text)
    except OSError:
        # Archivo bloqueado (antivirus, instancia anterior): usa un nombre unico.
        page = folder / f'interface-{os.getpid()}.html'
        _write_atomic(page, html_text)
    return page, background, html_text


def _begin_start(folder, force_safe):
    """Marca el arranque como 'en curso'. Si la marca ya existia, el arranque anterior
    no llego a cargar la interfaz: se activa el modo seguro y se limpia el perfil."""
    flag = folder / 'starting.flag'
    crashed = flag.exists()
    try:
        flag.write_text(str(time.time()), encoding='utf-8')
    except OSError:
        pass
    if crashed:
        get_logger().warning('El arranque anterior no termino; modo seguro y perfil limpio')
        shutil.rmtree(folder / 'WebView2', ignore_errors=True)
    return (crashed or force_safe), flag


def _clear_flag(flag):
    try:
        flag.unlink()
    except OSError:
        pass


def _run_webview(bridge, page, folder, safe, flag):
    import webview
    # WebView2 must use a writable profile, never the onefile extraction folder.
    profile = folder / 'WebView2'
    profile.mkdir(parents=True, exist_ok=True)
    if safe:
        extra = '--disable-gpu --disable-gpu-compositing'
        current = os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '')
        if extra not in current:
            os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (current + ' ' + extra).strip()
    bridge._fullscreen = False
    webview.settings['DRAG_REGION_SELECTOR'] = '.pywebview-drag-region'
    webview.settings['DRAG_REGION_DIRECT_TARGET_ONLY'] = True
    bridge._window = webview.create_window(
        'SSTool+', url=page.as_uri(), js_api=bridge,
        width=1180, height=820, min_size=(760, 540), frameless=True,
        easy_drag=False, resizable=True, fullscreen=False, background_color='#0a0607')

    def remove_native_frame():
        if sys.platform != 'win32':
            return
        try:
            native = bridge._window.native
            # Fullscreen/restore can reset WinForms' border; reapply on transitions.
            from System import Action
            from System.Windows.Forms import FormBorderStyle
            borderless = getattr(FormBorderStyle, 'None')

            def enforce(*_):
                try:
                    if native.FormBorderStyle != borderless:
                        native.FormBorderStyle = borderless
                except Exception:  # noqa: BLE001 - un evento de ventana nunca debe lanzar
                    pass

            def install():
                # El icono del ejecutable (assets/SSToolPlus.ico) lo incrusta PyInstaller en BUILD_GLASS.bat.
                enforce()
                native.StyleChanged += enforce
                native.SizeChanged += enforce
            native.Invoke(Action(install))
        except Exception:  # noqa: BLE001
            get_logger().error('No se pudo quitar el marco nativo', exc_info=True)

    def on_loaded():
        bridge._loaded = True
        _clear_flag(flag)

    bridge._window.events.shown += remove_native_frame
    bridge._window.events.loaded += on_loaded
    webview.start(gui='edgechromium', debug=False, storage_path=str(profile))


def _tell_user(message):
    get_logger().warning(message)
    if sys.platform.startswith('win'):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'SSTool+', 0x40)
        except (AttributeError, OSError):
            pass


def _run_browser(bridge, html_text, background, flag):
    from ui.web_server import BrowserServer
    server = BrowserServer(bridge, html_text, background)
    _clear_flag(flag)
    server.run(on_open_failed=lambda url: _tell_user(
        'SSTool+ could not open your browser automatically. Open this address manually:\n' + url))


def run(argv=None):
    try:
        _run(argv)
    finally:
        if '--keep-data' not in (sys.argv[1:] if argv is None else argv):
            workspace.cleanup_on_exit()


def _run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    log = setup_logging()
    workspace.prepare_tools_root()
    folder = data_dir()
    safe, flag = _begin_start(folder, '--safe' in argv or os.environ.get('SSTOOL_SAFE') == '1')
    page, background, html_text = _prepare_page(folder, safe)
    bridge = Bridge()
    bridge._loaded = False
    mode = 'browser' if ('--browser' in argv or os.environ.get('SSTOOL_BROWSER') == '1') \
        else webview_runtime.ensure_runtime()
    if mode == 'webview':
        try:
            _run_webview(bridge, page, folder, safe, flag)
            _clear_flag(flag)
            return
        except Exception:  # noqa: BLE001 - falta pythonnet/WebView2, perfil danado, etc.
            log.error('La ventana nativa fallo', exc_info=True)
            if bridge._loaded:
                raise  # ya se uso la app: no abrir un navegador inesperadamente
        log.warning('Cambiando al modo navegador')
    _run_browser(bridge, html_text, background, flag)
