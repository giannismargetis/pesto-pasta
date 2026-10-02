import logging
import sys

from colorama import Fore, Style
from colorama import init as colorama_init

from .config import LOG_DIR

colorama_init()

_LOGGER_NAME = "pasta"
_configured = False


class _Formatter(logging.Formatter):
    COLORS = {
        "DEBUG": Fore.CYAN,
        "INFO": Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.RED + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        use_color = bool(color and sys.stdout and hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
        record.msg = f"{color}{record.msg}{Style.RESET_ALL}" if use_color else record.msg
        return super().format(record)


def setup_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    _configured = True
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger(_LOGGER_NAME)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    file_handler = logging.FileHandler(LOG_DIR / "pasta.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    root.addHandler(file_handler)
    if sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(_Formatter("%(message)s"))
        root.addHandler(stream_handler)


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{_LOGGER_NAME}.{name}" if name else _LOGGER_NAME)
