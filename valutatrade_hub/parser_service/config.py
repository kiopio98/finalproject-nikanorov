"""Настройки источников; ключи загружаются только из окружения."""

import os
from dataclasses import dataclass, field

from valutatrade_hub.infra.settings import SettingsLoader


@dataclass(frozen=True)
class ParserConfig:
    """Общие параметры запросов, валют и файлов."""

    EXCHANGERATE_API_KEY: str = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY", ""), repr=False
    )
    COINGECKO_API_KEY: str = field(
        default_factory=lambda: os.getenv("COINGECKO_API_KEY", ""), repr=False
    )
    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"
    EXCHANGERATE_OPEN_URL: str = "https://open.er-api.com/v6/latest/USD"
    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple = ("EUR", "GBP", "RUB")
    CRYPTO_CURRENCIES: tuple = ("BTC", "ETH", "SOL")
    CRYPTO_ID_MAP: dict = field(
        default_factory=lambda: {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
    )
    REQUEST_TIMEOUT: float = 10.0
    UPDATE_INTERVAL: int = 3600

    @property
    def RATES_FILE_PATH(self):
        """Путь текущего снимка."""
        return SettingsLoader().get("DATA_DIR") / "rates.json"

    @property
    def HISTORY_FILE_PATH(self):
        """Путь истории наблюдений."""
        return SettingsLoader().get("DATA_DIR") / "exchange_rates.json"
