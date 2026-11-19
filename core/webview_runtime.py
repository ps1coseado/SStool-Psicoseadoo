"""Deteccion e instalacion (con permiso) de Microsoft Edge WebView2 Runtime.

Windows personalizados (Tiny10/11, Atlas, ReviOS...) suelen quitar Edge y con el el
runtime que necesita la interfaz. En lugar de fallar con un error, SSTool+:
  1. busca el runtime instalado o uno portable junto al .exe (WebView2Runtime\\),
  2. si falta, pide permiso para instalar el oficial de Microsoft (se comprueba su
     firma digital antes de ejecutarlo),
  3. y si no se instala, abre la interfaz en el navegador (modo navegador).
"""
import os
import subprocess
import sys
import tempfile
import urllib.request

from core import net
from core.diagnostics import get_logger
from core.paths import is_windows, windows_directory

CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
BOOTSTRAPPER_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
RUNTIME_EXE = "msedgewebview2.exe"
MIN_BOOTSTRAPPER = 100 * 1024
MAX_BOOTSTRAPPER = 8 * 1024 * 1024
CREATE_NO_WINDOW = 0x08000000

MESSAGE_ES = (
    "SSTool+ necesita Microsoft Edge WebView2 Runtime y no esta instalado en este Windows.\n\n"
    "¿Instalar el runtime oficial de Microsoft ahora? (descarga pequena, requiere internet)\n\n"
    "Si eliges No, SSTool+ se abrira en tu navegador."
)
MESSAGE_EN = (
    "SSTool+ needs Microsoft Edge WebView2 Runtime, which is not installed on this Windows.\n\n"
    "Install the official Microsoft runtime now? (small download, internet required)\n\n"
    "If you choose No, SSTool+ will open in your browser."
)


def _registry_versions():
    """Versiones registradas del runtime (cadena vacia si no hay)."""
    try:
        import winreg
    except ImportError:
        return []
    found = []
    base = r"SOFTWARE\{}Microsoft\EdgeUpdate\Clients\{}"
    for hive, prefix in (
        (winreg.HKEY_LOCAL_MACHINE, "WOW6432Node\\"),
        (winreg.HKEY_LOCAL_MACHINE, ""),
        (winreg.HKEY_CURRENT_USER, ""),
    ):
        for view in (0, getattr(winreg, "KEY_WOW64_64KEY", 0)):
            try:
                with winreg.OpenKey(hive, base.format(prefix, CLIENT_GUID), 0,
                                    winreg.KEY_READ | view) as key:
                    version, _kind = winreg.QueryValueEx(key, "pv")
                    if version:
                        found.append(str(version))
            except OSError:
                continue
    return found


def _folder_has_runtime(folder):
    try:
        for current, _dirs, files in os.walk(folder):
            if RUNTIME_EXE in (name.lower() for name in files):
                return current
            if current[len(str(folder)):].count(os.sep) >= 3:
                _dirs[:] = []
    except OSError:
        pass
    return None


def _portable_runtime():
    """Runtime 'Fixed Version' puesto junto al .exe (carpeta WebView2Runtime)."""
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]))
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return None
    for name in entries:
        lowered = name.lower()
        if lowered == "webview2runtime" or lowered.startswith("microsoft.webview2.fixedversionruntime"):
            folder = _folder_has_runtime(os.path.join(base, name))
            if folder:
                return folder
    return None


def _installed_files_present():
    """Respaldo por archivos si el registro fue recortado por la personalizacion."""
    roots = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")]
    for root in filter(None, roots):
        application = os.path.join(root, "Microsoft", "EdgeWebView", "Application")
        if os.path.isdir(application) and _folder_has_runtime(application):
            return True
    return False


def detect():
    """Devuelve True si WebView2 puede usarse; configura el runtime portable si existe."""
    if not is_windows():
        return True
    override = os.environ.get("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER")
    if override and os.path.isfile(os.path.join(override, RUNTIME_EXE)):
        return True
    portable = _portable_runtime()
    if portable:
        os.environ["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = portable
        get_logger().info("Runtime WebView2 portable: %s", portable)
        return True
    if any(version not in ("", "0.0.0.0") for version in _registry_versions()):
        return True
    return _installed_files_present()


def _ask_install():
    try:
        import ctypes

        # LANG_SPANISH = 0x0A en los 10 bits bajos del idioma de la interfaz.
        spanish = (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x0A
        text = MESSAGE_ES if spanish else MESSAGE_EN
        # MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND
        return ctypes.windll.user32.MessageBoxW(None, text, "SSTool+", 0x00010024) == 6
    except (AttributeError, OSError, ValueError):
        return False


def _microsoft_signature_valid(path):
    """Fail-closed: solo se ejecuta si PowerShell confirma firma valida de Microsoft."""
    exe = os.path.join(windows_directory(), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if not os.path.isfile(exe):
        return False
    script = ("$s=Get-AuthenticodeSignature -LiteralPath $env:SS_FILE;"
              "if($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match 'O=Microsoft Corporation'){exit 0}else{exit 1}")
    try:
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            env=dict(os.environ, SS_FILE=path), timeout=60, creationflags=CREATE_NO_WINDOW,
            capture_output=True,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def install_runtime():
    """Descarga el bootstrapper oficial, valida su firma y lo ejecuta en silencio."""
    log = get_logger()
    handle, path = tempfile.mkstemp(prefix="sstool-wv2-", suffix=".exe")
    os.close(handle)
    try:
        request = urllib.request.Request(BOOTSTRAPPER_URL, headers={"User-Agent": "SSTool+/1.0"})
        with net.open_url(request, 30) as response:
            data = response.read(MAX_BOOTSTRAPPER + 1)
        if not (MIN_BOOTSTRAPPER <= len(data) <= MAX_BOOTSTRAPPER) or data[:2] != b"MZ":
            log.error("Bootstrapper WebView2 invalido (%d bytes)", len(data))
            return False
        with open(path, "wb") as output:
            output.write(data)
        if not _microsoft_signature_valid(path):
            log.error("Firma del bootstrapper WebView2 no verificada; no se ejecuta")
            return False
        result = subprocess.run([path, "/silent", "/install"], timeout=600,
                                creationflags=CREATE_NO_WINDOW)
        log.info("Bootstrapper WebView2 termino con codigo %s", result.returncode)
        return detect()
    except Exception:  # noqa: BLE001 - cualquier fallo lleva al modo navegador
        log.error("No se pudo instalar WebView2", exc_info=True)
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def ensure_runtime(interactive=True):
    """'webview' si se puede usar la ventana nativa, 'browser' en otro caso."""
    if detect():
        return "webview"
    get_logger().warning("WebView2 Runtime no encontrado")
    if interactive and _ask_install() and install_runtime():
        return "webview"
    return "browser"
