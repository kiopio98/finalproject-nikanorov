"""Изолированные HTTP-клиенты с одинаковым форматом результата."""

import time
from abc import ABC, abstractmethod

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import valid_number
from valutatrade_hub.parser_service.config import ParserConfig


class BaseApiClient(ABC):
    """Источник возвращает пары вида BTC_USD: float."""

    source = ""

    def __init__(self, config=None, session=None):
        self.config = config or ParserConfig()
        self.session = session or requests
        self.meta = {}

    def _request(self, url, **kwargs):
        started = time.monotonic()
        try:
            response = self.session.get(
                url, timeout=self.config.REQUEST_TIMEOUT, **kwargs
            )
            status = response.status_code
            if status == 429:
                raise ApiRequestError(f"{self.source}: лимит запросов (HTTP 429)")
            if status in (401, 403):
                raise ApiRequestError(
                    f"{self.source}: проверьте API-ключ (HTTP {status})"
                )
            if status != 200:
                raise ApiRequestError(f"{self.source}: HTTP {status}")
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("ожидался JSON-объект")
            self.meta = {
                "request_ms": round((time.monotonic() - started) * 1000),
                "status_code": status,
            }
            return data
        except requests.Timeout:
            raise ApiRequestError(f"{self.source}: превышено время ожидания") from None
        except requests.RequestException:
            # Текст requests может содержать URL с API-ключом. Его не журналируем.
            raise ApiRequestError(f"{self.source}: ошибка сети") from None
        except ValueError:
            raise ApiRequestError(f"{self.source}: некорректный JSON") from None

    @abstractmethod
    def fetch_rates(self) -> dict:
        """Получить конечные положительные курсы к USD."""


class CoinGeckoClient(BaseApiClient):
    """Курсы криптовалют из /simple/price."""

    source = "CoinGecko"

    def fetch_rates(self):
        """Одним запросом получить все настроенные криптовалюты."""
        mapping = self.config.CRYPTO_ID_MAP
        codes = self.config.CRYPTO_CURRENCIES
        headers = {}
        if self.config.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = self.config.COINGECKO_API_KEY
        data = self._request(
            self.config.COINGECKO_URL,
            headers=headers,
            params={
                "ids": ",".join(mapping[code] for code in codes),
                "vs_currencies": "usd",
                "include_last_updated_at": "true",
            },
        )
        try:
            result = {
                f"{code}_USD": valid_number(data[mapping[code]]["usd"])
                for code in codes
            }
        except (KeyError, TypeError, ValueError):
            raise ApiRequestError(
                "CoinGecko: ответ не содержит корректных курсов"
            ) from None
        self.meta["raw_ids"] = {code: mapping[code] for code in codes}
        self.meta["provider_updated_at"] = {
            code: data[mapping[code]].get("last_updated_at") for code in codes
        }
        return result


class ExchangeRateApiClient(BaseApiClient):
    """Фиатные курсы: ключевой v6 либо официальный Open Access API."""

    source = "ExchangeRate-API"

    def fetch_rates(self):
        """Инвертировать USD→валюта в единый формат валюта→USD."""
        key = self.config.EXCHANGERATE_API_KEY
        url = (
            f"{self.config.EXCHANGERATE_API_URL}/{key}/latest/USD"
            if key
            else self.config.EXCHANGERATE_OPEN_URL
        )
        data = self._request(url)
        try:
            if data.get("result") != "success" or data.get("base_code") != "USD":
                raise ValueError("неверный ответ")
            rates = data.get("conversion_rates", data.get("rates"))
            result = {
                f"{code}_USD": valid_number(1 / valid_number(rates[code]))
                for code in self.config.FIAT_CURRENCIES
            }
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            raise ApiRequestError(
                "ExchangeRate-API: неверная база, API-ключ или формат курсов"
            ) from None
        self.meta["provider_updated_at"] = data.get("time_last_update_utc")
        self.meta["open_access"] = not bool(key)
        return result
