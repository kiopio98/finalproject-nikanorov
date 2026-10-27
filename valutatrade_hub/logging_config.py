"""Раздельные ротируемые JSON-журналы операций и парсера."""

import json
import logging
from logging.handlers import RotatingFileHandler

from valutatrade_hub.core.utils import utc_now
from valutatrade_hub.infra.settings import SettingsLoader


class JsonFormatter(logging.Formatter):
    """Одна запись JSON на строку, без аргументов команд и секретов."""

    def format(self, record):
        payload = {
            "timestamp": utc_now(),
            "level": record.levelname,
            **getattr(record, "event", {"message": record.getMessage()}),
        }
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def get_logger(name):
    """Подключить файловый обработчик один раз на каталог журнала."""
    settings = SettingsLoader()
    directory = settings.get("LOG_DIR")
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"valutatrade.{name}")
    path = str(directory / f"{name}.log")
    if not any(getattr(h, "baseFilename", None) == path for h in logger.handlers):
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        handler = RotatingFileHandler(
            path,
            maxBytes=settings.get("LOG_MAX_BYTES"),
            backupCount=settings.get("LOG_BACKUP_COUNT"),
            encoding="utf-8",
        )
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
