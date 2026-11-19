"""Carpeta Tools (con el origen de cada descarga) y limpieza de todo lo creado al cerrar."""
import datetime
import logging
import os
import shutil
import subprocess
import sys

from core import launcher
from core.config import TOOLS_ROOT
from core.diagnostics import get_logger
from core.paths import APP_FOLDER, data_dir
from core.tool_info import tool_info

MARKER = ".sstool-created"
SOURCES_FILE = "ORIGEN.txt"


def prepare_tools_root():
    """Crea Tools/ al iniciar. Solo se marca como 'creada por la app' si no existia antes,
    asi nunca se borra una carpeta que ya tenia contenido del usuario."""
    existed = os.path.isdir(os.path.join(launcher.downloads_directory(), TOOLS_ROOT))
    root = launcher.tools_root_directory()  # puede crearla; por eso se comprueba antes
    try:
        os.makedirs(root, exist_ok=True)
        if not existed:
            open(os.path.join(root, MARKER), "w").close()
    except OSError:
        get_logger().warning("No se pudo preparar %s", root, exc_info=True)
    return root


def record_source(category_id, tool):
    """Anota en Tools/<categoria>/ORIGEN.txt de donde proviene cada herramienta descargada."""
    try:
        path = launcher.resolve_tool_path(category_id, tool)
        if not path or not os.path.exists(path):
            return
        info = tool_info(tool)
        folder = os.path.dirname(path)
        target = os.path.join(folder, SOURCES_FILE)
        block = "\n".join([
            f"[{tool['name']}]",
            f"Archivo / File: {os.path.basename(path)}",
            f"Origen / Source: {info['source'] or 'SSTool+'}",
            f"Version: {info['version'] or 'latest'}",
            f"Pagina oficial / Official page: {info['page'] or '-'}",
            f"Descarga / Download: {info['link'] or '-'}",
            f"Fecha / Date: {datetime.datetime.now():%Y-%m-%d %H:%M}",
        ])
        blocks = []
        if os.path.exists(target):
            with open(target, encoding="utf-8") as handle:
                blocks = [b for b in handle.read().split("\n\n") if b.strip()]
        blocks = [b for b in blocks if b.splitlines()[0] != f"[{tool['name']}]"] + [block]
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("\n\n".join(blocks) + "\n")
    except Exception:  # noqa: BLE001 - anotar el origen nunca debe romper una descarga
        get_logger().warning("No se pudo anotar el origen de %s", tool.get("name"), exc_info=True)


def _release_logs():
    import faulthandler
    from core import diagnostics
    logger = get_logger()
    for handler in list(logger.handlers):
        try:
            handler.close()
        finally:
            logger.removeHandler(handler)
    try:
        faulthandler.disable()
        if getattr(diagnostics, "_fault_file", None):
            diagnostics._fault_file.close()
    except Exception:  # noqa: BLE001
        pass
    logging.shutdown()


def _safe_target(path):
    return os.path.basename(os.path.normpath(path)).lower() in {TOOLS_ROOT.lower(), APP_FOLDER.lower(), "." + APP_FOLDER.lower()}


def cleanup_on_exit():
    """Elimina carpetas y archivos creados por la app (Tools creada por ella y datos/perfil).
    Lo guardado manualmente en Descargas no se toca. SSTOOL_KEEP=1 lo desactiva."""
    if os.environ.get("SSTOOL_KEEP") == "1":
        return
    targets = []
    try:
        root = launcher.tools_root_directory()
        if os.path.exists(os.path.join(root, MARKER)):
            targets.append(root)
    except Exception:  # noqa: BLE001
        pass
    try:
        targets.append(str(data_dir()))
    except OSError:
        pass
    _release_logs()
    targets = [t for t in dict.fromkeys(targets) if _safe_target(t)]
    for target in targets:
        shutil.rmtree(target, ignore_errors=True)
    left = [t for t in targets if os.path.exists(t)]
    if left and sys.platform == "win32":
        # Archivos aun bloqueados (WebView2 cerrandose / herramienta abierta): reintento diferido.
        command = "ping -n 6 127.0.0.1 >nul & " + " & ".join(f'rmdir /s /q "{t}"' for t in left)
        try:
            subprocess.Popen(["cmd", "/c", command], close_fds=True,
                             creationflags=0x08000000 | 0x00000008)  # NO_WINDOW | DETACHED
        except OSError:
            pass
