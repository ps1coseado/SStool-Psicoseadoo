"""Acceso HTTPS tolerante a Windows personalizados.

* Si el almacen de certificados del sistema esta desactualizado, se reintenta con el
  paquete de certifi. La verificacion TLS NUNCA se desactiva.
* Un reintento unico para cortes de conexion transitorios.
* Mensajes de error comprensibles en lugar de excepciones tecnicas.
"""
import errno
import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request

RETRY_DELAY = 1.5
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_TRANSIENT_ERRORS = (
    ConnectionResetError,
    ConnectionAbortedError,
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
)


def is_certificate_error(exc):
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError) or isinstance(exc, ssl.SSLCertVerificationError):
        return True
    return "CERTIFICATE_VERIFY_FAILED" in str(reason)


def _certifi_context():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 - certifi es opcional
        return None


def open_url(request, timeout):
    """urlopen con respaldo de certificados (sin saltarse la verificacion)."""
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except (urllib.error.URLError, ssl.SSLError) as exc:
        if not is_certificate_error(exc):
            raise
        context = _certifi_context()
        if context is None:
            raise
        return urllib.request.urlopen(request, timeout=timeout, context=context)


def is_transient(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _TRANSIENT_STATUS
    return isinstance(exc, _TRANSIENT_ERRORS)


def retry_once(function):
    """Ejecuta function(); si falla de forma transitoria, la repite una vez."""
    try:
        return function()
    except Exception as exc:  # noqa: BLE001
        if not is_transient(exc):
            raise
    time.sleep(RETRY_DELAY)
    return function()


def describe_error(exc):
    """Texto claro para el usuario; el detalle tecnico queda en el log."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"el servidor respondio HTTP {exc.code}; el enlace puede haber cambiado"
    if is_certificate_error(exc):
        return ("Windows no confia en el certificado del servidor. Revisa la fecha y hora "
                "del sistema o actualiza los certificados raiz")
    if isinstance(exc, urllib.error.URLError):
        inner = exc.reason
        if isinstance(inner, socket.gaierror):
            return "no se pudo resolver el nombre del servidor (sin internet, DNS o proxy)"
        if isinstance(inner, (socket.timeout, TimeoutError)):
            return "el servidor tardo demasiado en responder"
        return f"error de red: {inner}"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "la conexion se agoto; vuelve a intentarlo"
    if isinstance(exc, http.client.HTTPException):
        return "la conexion se corto durante la descarga; vuelve a intentarlo"
    if isinstance(exc, ssl.SSLError):
        return f"error TLS/SSL: {exc}"
    if isinstance(exc, PermissionError):
        return ("Windows denego el acceso al archivo. Un antivirus o una carpeta protegida "
                "puede estar bloqueandolo")
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOSPC:
        return "no hay espacio libre en el disco"
    if isinstance(exc, FileNotFoundError):
        return "el archivo desaparecio durante la operacion (posible antivirus)"
    return str(exc) or exc.__class__.__name__
