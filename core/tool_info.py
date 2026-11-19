"""Metadatos de herramientas (origen, version, enlaces) y traduccion de avisos al ingles."""
import os
import re
import urllib.parse

APP_VERSION = "1.0.0"
# Repositorio donde se publican las versiones de SSTool+ (se consulta la ultima release).
UPDATE_REPO = "Psicosiadov2/SStool-Psicoseadoo"
AUTHOR_GITHUB = "https://github.com/Psicosiadov2/"

_GH = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/", re.I)
_RAW = re.compile(r"^https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/", re.I)
_VER = re.compile(r"(?<![\w.])v?\.?(\d+(?:\.\d+){1,3}[a-z]?)(?![\w])", re.I)


def download_link(tool):
    """Enlace de descarga oficial del catalogo (None si es script interno o comando)."""
    return tool.get("mediafire_page") or tool.get("url") or tool.get("download_url") or tool.get("browser_url")


def _nirsoft_page(url):
    m = re.match(r"^https?://www\.nirsoft\.net/utils/([\w\-]+?)(?:-x64|_x64)?\.(?:zip|exe)$", url, re.I)
    return f"https://www.nirsoft.net/utils/{m.group(1)}.html" if m else None


def tool_info(tool):
    """Devuelve dict(source, page, link, version). Nunca inventa datos: version None = ultima publicada."""
    link = re.sub(r"[?&]utm_source=[^&]*$", "", download_link(tool) or "") or None
    probe = tool.get("url") or tool.get("download_url") or ""
    page, source, version = None, None, None
    m = _GH.match(probe) or _RAW.match(probe)
    if m:
        owner, repo = m.group(1), m.group(2)
        page, source = f"https://github.com/{owner}/{repo}", f"GitHub · {owner}/{repo}"
        if _GH.match(probe):
            version = m.group(3)
    elif "nirsoft.net" in probe:
        page, source = _nirsoft_page(probe) or "https://www.nirsoft.net/", "NirSoft"
    elif "ericzimmermanstools" in probe:
        page, source = "https://ericzimmerman.github.io/", "Eric Zimmerman"
    elif tool.get("browser_url"):
        host = urllib.parse.urlparse(tool["browser_url"]).hostname or ""
        page, source = tool["browser_url"], host.replace("www.", "")
    elif tool.get("mediafire_page"):
        page, source = tool["mediafire_page"], "MediaFire"
    elif "dotnet.microsoft.com" in probe:
        page, source = "https://dotnet.microsoft.com/download", "Microsoft .NET"
    elif "aka.ms/vc14" in probe:
        page, source = "https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist", "Microsoft"
    elif "oracle.com" in probe:
        page, source = "https://www.java.com/download/", "Oracle Java"
    elif "voidtools.com" in probe:
        page, source = "https://www.voidtools.com/", "voidtools"
    elif "discordapp.com" in probe:
        page, source = None, "Discord CDN"
    elif probe:
        host = (urllib.parse.urlparse(probe).hostname or "").replace("www.", "")
        page = f"https://{host}/" if host else None
        source = host or None
    elif tool.get("mediafire_page"):
        page, source = tool["mediafire_page"], "MediaFire"
    elif tool.get("embedded_script") is not None or tool.get("cmd_command") or tool.get("native_command") or tool.get("bundled"):
        source = "SSTool+"
    if version is None:
        for text in (os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(probe).path)), tool.get("name", "")):
            v = _VER.search(text)
            if v:
                version = v.group(1)
                break
    if version and not version.lower().startswith("v") and re.match(r"\d", version):
        version = "v" + version
    return dict(source=source, page=page, link=link, version=version)


def compare_versions(current, latest):
    """True si 'latest' es posterior a 'current'. Tolera prefijo v y sufijos."""
    def parts(v):
        return [int(n) for n in re.findall(r"\d+", str(v))[:4]] or [0]
    a, b = parts(current), parts(latest)
    n = max(len(a), len(b))
    return (a + [0] * (n - len(a))) < (b + [0] * (n - len(b)))


# Avisos del nucleo (escritos en espanol) -> ingles. Orden: primero los mas especificos.
_EN = [
    (r"^Descargando y verificando (.+)\.\.\.$", r"Downloading and verifying \1..."),
    (r"^(.+) se descargo y solicito permisos de administrador mediante UAC\.$", r"\1 was downloaded and requested administrator permission via UAC."),
    (r"^(.+) se descargo y se abrio correctamente\.$", r"\1 was downloaded and opened successfully."),
    (r"^(.+) solicito permisos de administrador mediante UAC\.$", r"\1 requested administrator permission via UAC."),
    (r"^(.+) se abrio en CMD como administrador\.$", r"\1 was opened in CMD as administrator."),
    (r"^(.+) se abrio en el navegador\.$", r"\1 was opened in the browser."),
    (r"^(.+) se abrio correctamente\.$", r"\1 opened successfully."),
    (r"^No se pudo actualizar (.+); se abre la copia ya descargada\.$", r"Could not update \1; opening the existing copy."),
    (r"^No se pudo descargar o iniciar (.+):\n", r"Could not download or start \1:\n"),
    (r"^'(.+)' todavia no tiene funcion configurada\.\nRuta esperada:", r"'\1' has no function configured yet.\nExpected path:"),
    (r"el servidor respondio HTTP (\d+); el enlace puede haber cambiado", r"the server answered HTTP \1; the link may have changed"),
    (r"la verificacion SHA-256 fallo; el archivo no se abrira por seguridad", "SHA-256 verification failed; the file will not be opened for safety"),
    (r"el archivo incluido con SSTool\+ no se encontro; vuelve a descargar o reinstalar SSTool\+", "the file bundled with SSTool+ was not found; download or reinstall SSTool+ again"),
    (r"el archivo descargado no es un ejecutable valido de Windows", "the downloaded file is not a valid Windows executable"),
    (r"el ejecutable esperado no se encontro despues de la descarga", "the expected executable was not found after download"),
    (r"el archivo descargado no es un ZIP valido", "the downloaded file is not a valid ZIP"),
    (r"la descarga supera el limite de 512 MB", "the download exceeds the 512 MB limit"),
    (r"la descarga excedio 10 minutos; vuelve a intentarlo", "the download exceeded 10 minutes; please try again"),
    (r"el servidor devolvio un archivo vacio", "the server returned an empty file"),
    (r"descarga incompleta; vuelve a pulsar el boton para reintentar", "incomplete download; press the button again to retry"),
    (r"esta herramienta todavia no tiene enlace de descarga", "this tool has no download link yet"),
    (r"esta herramienta no tiene una ruta de instalacion configurada", "this tool has no install path configured"),
    (r"el ejecutable instalado no coincide con el hash esperado", "the installed executable does not match the expected hash"),
    (r"Windows no pudo abrir el navegador predeterminado", "Windows could not open the default browser"),
    (r"Windows no pudo iniciar el archivo \(ShellExecute: (\d+)\)\. Comprueba el aviso UAC, las dependencias y el historial de proteccion de Windows\.",
     r"Windows could not start the file (ShellExecute: \1). Check the UAC prompt, dependencies and Windows protection history."),
    (r"no se pudo resolver el nombre del servidor \(sin internet, DNS o proxy\)", "could not resolve the server name (no internet, DNS or proxy)"),
    (r"el servidor tardo demasiado en responder", "the server took too long to respond"),
    (r"la conexion se agoto; vuelve a intentarlo", "the connection timed out; please try again"),
    (r"la conexion se corto durante la descarga; vuelve a intentarlo", "the connection dropped during download; please try again"),
    (r"error de red:", "network error:"),
    (r"Windows no confia en el certificado del servidor\. Revisa la fecha y hora del sistema o actualiza los certificados raiz",
     "Windows does not trust the server certificate. Check the system date and time or update the root certificates"),
    (r"Windows denego el acceso al archivo\. Un antivirus o una carpeta protegida puede estar bloqueandolo",
     "Windows denied access to the file. An antivirus or protected folder may be blocking it"),
    (r"no hay espacio libre en el disco", "there is no free disk space"),
    (r"el archivo desaparecio durante la operacion \(posible antivirus\)", "the file disappeared during the operation (possible antivirus)"),
    (r"no se pudo obtener ", "could not get "),
    (r"MediaFire no devolvio un enlace de descarga valido", "MediaFire did not return a valid download link"),
    (r"el ZIP contiene una ruta insegura", "the ZIP contains an unsafe path"),
]
_EN = [(re.compile(p, re.S), r) for p, r in _EN]


def to_english(message):
    text = str(message)
    for pattern, repl in _EN:
        text = pattern.sub(repl, text)
    return text
