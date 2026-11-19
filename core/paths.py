"""Rutas de datos con alternativas para Windows personalizados (Tiny10, Atlas, etc.).

En algunos sistemas recortados LOCALAPPDATA no existe, apunta a una carpeta de solo
lectura o falta SystemRoot. Aqui se elige siempre la primera ubicacion realmente
escribible en lugar de fallar al arrancar.
"""
import os
import sys
import tempfile
from pathlib import Path

APP_FOLDER = "PsicoseadoSSTool"


def is_windows():
    return sys.platform.startswith("win")


def writable_directory(path):
    """True si se puede crear la carpeta y escribir un archivo de prueba."""
    try:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir():
    """Carpeta persistente de la app (logs, perfil WebView2, pagina local)."""
    candidates = []
    for variable in ("LOCALAPPDATA", "APPDATA"):
        value = os.environ.get(variable)
        if value:
            candidates.append(Path(value) / APP_FOLDER)
    candidates.append(Path(tempfile.gettempdir()) / APP_FOLDER)
    try:
        candidates.append(Path.home() / f".{APP_FOLDER}")
    except (RuntimeError, KeyError):
        pass
    for candidate in candidates:
        if writable_directory(candidate):
            return candidate
    raise OSError("No hay ninguna carpeta escribible para los datos de SSTool+.")


def windows_directory():
    """Carpeta de Windows aunque falten variables de entorno."""
    for variable in ("SystemRoot", "windir"):
        value = os.environ.get(variable)
        if value and os.path.isdir(value):
            return value
    if is_windows():
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(260)
            if ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, 260):
                return buffer.value
        except (AttributeError, OSError):
            pass
    return r"C:\Windows"


def ensure_system_path():
    """Anade System32 y PowerShell al PATH si una personalizacion los quito.

    Muchos comandos del catalogo empiezan por ``powershell`` o ``cmd``; con un PATH
    recortado fallarian aunque el programa exista.
    """
    if not is_windows():
        return []
    root = windows_directory()
    wanted = [
        os.path.join(root, "System32"),
        root,
        os.path.join(root, "System32", "Wbem"),
        os.path.join(root, "System32", "WindowsPowerShell", "v1.0"),
    ]
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    known = {p.rstrip("\\/").lower() for p in parts}
    missing = [p for p in wanted if p.lower() not in known and os.path.isdir(p)]
    if missing:
        os.environ["PATH"] = os.pathsep.join(parts + missing)
    return missing
