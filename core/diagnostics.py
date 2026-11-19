"""Registro persistente y captura de fallos para un .exe sin consola."""
import faulthandler
import logging
import logging.handlers
import sys
import threading

from core.paths import data_dir

LOGGER_NAME = "sstool"
_fault_file = None
_configured = False


def get_logger():
    return logging.getLogger(LOGGER_NAME)


def setup_logging():
    """Configura sstool.log (rotativo), excepthooks y faulthandler. Nunca lanza."""
    global _fault_file, _configured
    if _configured:
        return get_logger()
    _configured = True
    logger = get_logger()
    logger.setLevel(logging.INFO)
    try:
        folder = data_dir()
        handler = logging.handlers.RotatingFileHandler(
            folder / "sstool.log", maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        try:
            crash = folder / "crash-native.log"
            if crash.exists() and crash.stat().st_size > 256 * 1024:
                crash.unlink()
            _fault_file = open(crash, "a", encoding="utf-8")
            faulthandler.enable(file=_fault_file, all_threads=True)
        except (OSError, RuntimeError, ValueError):
            _fault_file = None
    except OSError:
        logger.addHandler(logging.NullHandler())

    def _log_uncaught(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    def _log_thread(args):
        if args.exc_type is SystemExit:
            return
        logger.error(
            "Uncaught exception in thread %s", getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _log_uncaught
    threading.excepthook = _log_thread
    logger.info("SSTool+ start (python %s, platform %s)", sys.version.split()[0], sys.platform)
    return logger
