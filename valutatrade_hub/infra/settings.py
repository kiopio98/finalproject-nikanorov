"""Настройки из pyproject.toml и переменных окружения."""

import os
import tomllib
from pathlib import Path


class SettingsLoader:
    """Единственный загрузчик настроек процесса."""

    _instance = None
    DEFAULTS = {
        "DATA_DIR": "data",
        "LOG_DIR": "logs",
        "RATES_TTL_SECONDS": 300,
        "DEFAULT_BASE_CURRENCY": "USD",
        "LOG_MAX_BYTES": 1048576,
        "LOG_BACKUP_COUNT": 3,
    }

    def __new__(cls):
        # __new__ достаточно: метакласс для одного класса усложнил бы код.
        if cls._instance is None:
            instance = super().__new__(cls)
            instance.reload()
            cls._instance = instance
        return cls._instance

    def reload(self):
        """Перечитать конфигурацию; относительные пути считаются от cwd."""
        config = Path(os.getenv("VALUTATRADE_CONFIG", "pyproject.toml"))
        values = dict(self.DEFAULTS)
        if config.exists():
            with config.open("rb") as file:
                values.update(tomllib.load(file).get("tool", {}).get("valutatrade", {}))
        elif "VALUTATRADE_CONFIG" in os.environ:
            raise ValueError(f"Файл конфигурации не найден: {config}")
        for key in ("DATA_DIR", "LOG_DIR"):
            values[key] = Path(os.getenv(f"VALUTATRADE_{key}", values[key])).resolve()
        for key in ("RATES_TTL_SECONDS", "LOG_MAX_BYTES", "LOG_BACKUP_COUNT"):
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{key} должен быть положительным целым числом")
        self._values = values

    def get(self, key, default=None):
        """Получить настройку либо значение по умолчанию."""
        return self._values.get(key, default)
