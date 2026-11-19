# SSTool+ — fondo, estabilidad y compatibilidad (Windows personalizados)

## Fondo
- Fondo espacial rojo animado: `assets/starfield.js` pinta un canvas fijo detrás de toda la interfaz con
  nebulosas rojas, estrellas en varias capas con parpadeo, estrellas fugaces y chispas. Las capas también
  se desplazan suavemente con el puntero. `ui/web_app.py` incrusta el script al final de la página.
- `BACKGROUND_CSS` mantiene un degradado rojo profundo y `background.jpg` como textura muy tenue
  (`--bg-dim:.985`; 0 = sin oscurecer). Si el canvas no se pudiera crear, quedan el degradado y la imagen.
- En modo seguro o con `html.low-effects` se dibuja el mismo campo de estrellas pero sin movimiento ni
  meteoros (menos CPU/GPU). El fondo sigue animado aunque Windows tenga activado "reducir movimiento":
  ese ajuste se respeta en el resto de la interfaz, pero no apaga el starfield.
- Ajustes → «Sin animaciones (versión optimizada)»: activa `html.no-animations` y `html.low-effects`,
  cancela las animaciones en curso, salta el intro y deja el starfield estático. También desactiva las
  transiciones CSS, la estela del ratón y los efectos de las tarjetas. Se guarda en
  `localStorage` (`noAnimations`) y se aplica antes de pintar la interfaz.
- `background.jpg` se copia junto a `interface.html` en la carpeta de datos; `preview.html` la lleva
  incrustada y también incluye el starfield para verlo sin instalar nada.

## Compatibilidad con Windows personalizados (Tiny10/11, Atlas, ReviOS…)
| Problema típico | Qué hace ahora |
|---|---|
| Sin Edge / sin WebView2 Runtime (la app no abría) | Detecta el runtime (registro + archivos + carpeta portable `WebView2Runtime\` junto al .exe). Si falta, **pide permiso** para instalar el oficial (se verifica la firma de Microsoft antes de ejecutarlo). Si dices que no, o falla, abre la **misma interfaz en el navegador** (modo navegador, solo `127.0.0.1`). |
| Sin códec H.264 (ediciones N) o decodificador colgado | La intro se salta sola a los 4 s si el video no arrancó (antes esperaba 10 s). |
| `LOCALAPPDATA` ausente o de solo lectura | Cadena de carpetas de respaldo: LOCALAPPDATA → APPDATA → TEMP → carpeta del usuario. |
| Descargas redirigida/bloqueada | Las herramientas se guardan en la carpeta de datos de la app. |
| PATH recortado (`powershell`/`cmd` no se encuentran) | Al iniciar se añaden System32, Wbem y PowerShell al PATH del proceso si faltan. |
| Certificados raíz desactualizados | Reintenta con el paquete de `certifi` (la verificación TLS **nunca** se desactiva) y explica el error (fecha/hora, DNS…). |
| Python/EXE sin Tcl/Tk | La interfaz activa ya no importa `tkinter`; el .exe se compila sin él (más pequeño, arranca antes). |

## Estabilidad
- **Una sola instancia** (mutex) — evita dos procesos peleando por el perfil de WebView2; trae al frente la ventana abierta.
- **Recuperación de arranque**: si un arranque no llegó a cargar la interfaz, el siguiente usa *modo seguro*
  (GPU desactivada, sin intro ni efectos) y recrea el perfil de WebView2. Forzable con `--safe`; `--browser` fuerza el modo navegador.
- Registro persistente `%LOCALAPPDATA%\PsicoseadoSSTool\sstool.log` (rotativo) + `crash-native.log` (faulthandler) y
  captura de excepciones en hilos; antes un fallo en un hilo se perdía en un .exe sin consola.
- `interface.html` se escribe de forma atómica; si está bloqueado usa un nombre alterno.
- Descargas: 1 reintento ante cortes de conexión/5xx, `Content-Length` inválido tolerado, y `IncompleteRead` y
  similares ya no escapan del hilo (mensaje claro en vez de excepción cruda).
- Eventos de ventana (marco nativo) envueltos para que un fallo de WinForms no cierre la app.

## Lo que NO cambió
Categorías, IDs, descripciones, hashes y funciones del catálogo, `core/data.py` y la lógica de Zimmerman siguen igual.

## Pendiente de probar en Windows real
No hay Windows ni WebView2 en el entorno donde se hizo esto: la lógica se probó con tests (64 pasan; incluyen
un servidor de modo navegador real) pero **la instalación de WebView2, el mutex y la ventana nativa deben probarse
en una máquina Windows** (idealmente una VM de Tiny11/Atlas sin Edge) antes de publicar.
