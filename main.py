"""
SSTool - punto de entrada.

Requisitos (instalar en tu PC antes de correr o compilar):
    pip install -r requirements.txt

Opciones de linea de comandos (solo diagnostico):
    --browser   abre la interfaz en el navegador (sin WebView2)
    --safe      sin intro ni efectos y con GPU desactivada

Ejecutar en desarrollo:
    python main.py

Compilar a .exe para Windows:
    BUILD_EXE.bat

El .exe resultante queda en dist/PsicoseadoSSTool.exe. Al abrirlo la primera vez,
la app crea automaticamente la carpeta tools/<categoria>/ al lado del .exe.
"""

def main():
    import multiprocessing
    multiprocessing.freeze_support()
    # Keep imports inside the guard: missing bundled modules must also be logged.
    from core.startup_errors import report_error
    try:
        from core.diagnostics import setup_logging
        from core.elevation import ensure_admin
        from core.paths import ensure_system_path
        from core.windows_shell import acquire_single_instance, configure_process_identity
        from ui.web_app import run
        setup_logging()
        if ensure_admin():
            if not acquire_single_instance():
                return 0  # ya hay una ventana abierta; se trajo al frente
            ensure_system_path()
            configure_process_identity()
            run()
        return 0
    except Exception:
        import sys
        report_error(*sys.exc_info())
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
