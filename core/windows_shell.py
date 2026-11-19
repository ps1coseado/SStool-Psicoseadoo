"""Integracion visual de PsicoseadoSSTool con el shell de Windows."""

import ctypes
import os
import sys

try:  # tkinter solo lo usa la interfaz antigua; la actual (WebView2) no lo necesita.
    import tkinter as tk
    _TclError = tk.TclError
except ImportError:  # Python recortado o sin Tcl/Tk
    tk = None
    _TclError = RuntimeError

from core.config import APP_USER_MODEL_ID


GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SW_MINIMIZE = 6
SPI_GETWORKAREA = 0x0030


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
_instance_mutex = None


def acquire_single_instance(name="Local\\Psicoseado.SSTool.SingleInstance"):
    """False si ya hay otra instancia abierta (se trae su ventana al frente).

    Dos instancias comparten el perfil de WebView2 y pueden bloquearlo o corromperlo.
    Si el mutex no se puede crear se permite continuar: nunca bloquea el arranque.
    """
    global _instance_mutex
    if not sys.platform.startswith("win"):
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return True
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            _focus_existing_window()
            return False
        _instance_mutex = handle  # se libera al cerrar el proceso
    except (AttributeError, OSError):
        return True
    return True


def _focus_existing_window(title="SSTool+"):
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
    except (AttributeError, OSError):
        pass


def configure_process_identity():
    """Asigna identidad estable para el icono y agrupacion en la taskbar."""
    if not sys.platform.startswith("win"):
        return
    try:
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        set_app_id(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def force_taskbar_window(window):
    """Hace visible en la taskbar una ventana con barra personalizada."""
    if not sys.platform.startswith("win"):
        return
    try:
        window.update_idletasks()
        user32 = ctypes.windll.user32
        get_parent = user32.GetParent
        get_parent.argtypes = [ctypes.c_void_p]
        get_parent.restype = ctypes.c_void_p
        get_window_long = user32.GetWindowLongW
        get_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
        get_window_long.restype = ctypes.c_long
        set_window_long = user32.SetWindowLongW
        set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        set_window_long.restype = ctypes.c_long
        set_window_pos = user32.SetWindowPos
        set_window_pos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        set_window_pos.restype = ctypes.c_bool

        native_id = window.winfo_id()
        handle = get_parent(native_id) or native_id
        style = get_window_long(handle, GWL_EXSTYLE)
        style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
        set_window_long(handle, GWL_EXSTYLE, style)
        set_window_pos(
            handle,
            0,
            0,
            0,
            0,
            0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )
    except (AttributeError, OSError):
        pass


def minimize_taskbar_window(window):
    """Minimiza el HWND real mediante Windows, sin crear el icono antiguo de Tk."""
    if not sys.platform.startswith("win"):
        return False
    try:
        window.update_idletasks()
        force_taskbar_window(window)

        user32 = ctypes.windll.user32
        get_parent = user32.GetParent
        get_parent.argtypes = [ctypes.c_void_p]
        get_parent.restype = ctypes.c_void_p
        show_window = user32.ShowWindow
        show_window.argtypes = [ctypes.c_void_p, ctypes.c_int]
        show_window.restype = ctypes.c_bool

        native_id = window.winfo_id()
        handle = get_parent(native_id) or native_id
        show_window(handle, SW_MINIMIZE)
        return True
    except (AttributeError, OSError, _TclError):
        return False


def get_work_area(window):
    """Devuelve el area util del monitor sin cubrir la barra de tareas."""
    if sys.platform.startswith("win"):
        try:
            rectangle = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rectangle), 0
            ):
                return (
                    rectangle.left,
                    rectangle.top,
                    rectangle.right - rectangle.left,
                    rectangle.bottom - rectangle.top,
                )
        except (AttributeError, OSError):
            pass
    return (
        window.winfo_vrootx(),
        window.winfo_vrooty(),
        window.winfo_vrootwidth(),
        window.winfo_vrootheight(),
    )


def asset_path(filename):
    """Devuelve la ruta de un asset en codigo fuente, PyInstaller o Nuitka."""
    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    root = pyinstaller_root or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    return os.path.join(root, "assets", filename)
