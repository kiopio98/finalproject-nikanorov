"""Иерархия валют и единый реестр кодов."""

from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError
from valutatrade_hub.core.utils import valid_number


class Currency(ABC):
    """Общая информация о валюте."""

    def __init__(self, name: str, code: str):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Название валюты не может быть пустым")
        if (
            not isinstance(code, str)
            or not code.isascii()
            or not code.isalpha()
            or not code.isupper()
            or not 2 <= len(code) <= 5
        ):
            raise ValueError("Код валюты: 2–5 латинских букв в верхнем регистре")
        self.name = name.strip()
        self.code = code

    @abstractmethod
    def get_display_info(self) -> str:
        """Описание конкретного вида валюты."""


class FiatCurrency(Currency):
    """Валюта, выпускаемая государством."""

    def __init__(self, name, code, issuing_country):
        super().__init__(name, code)
        if not isinstance(issuing_country, str) or not issuing_country.strip():
            raise ValueError("Не указана страна-эмитент")
        self.issuing_country = issuing_country.strip()

    def get_display_info(self):
        """Описание с указанием эмитента."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта; неизвестная капитализация обозначается нулём."""

    def __init__(self, name, code, algorithm, market_cap=0.0):
        super().__init__(name, code)
        if not isinstance(algorithm, str) or not algorithm.strip():
            raise ValueError("Не указан алгоритм")
        self.algorithm = algorithm.strip()
        self.market_cap = valid_number(market_cap, positive=False)

    def get_display_info(self):
        """Описание с алгоритмом и последней известной капитализацией."""
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {self.market_cap:.3g})"
        )


_REGISTRY = {
    item.code: item
    for item in (
        FiatCurrency("US Dollar", "USD", "United States"),
        FiatCurrency("Euro", "EUR", "Eurozone"),
        FiatCurrency("Pound Sterling", "GBP", "United Kingdom"),
        FiatCurrency("Russian Ruble", "RUB", "Russia"),
        CryptoCurrency("Bitcoin", "BTC", "SHA-256"),
        CryptoCurrency("Ethereum", "ETH", "Proof of Stake"),
        CryptoCurrency("Solana", "SOL", "Proof of History / Proof of Stake"),
    )
}


def get_currency(code: str) -> Currency:
    """Нормализовать пользовательский ввод и найти валюту."""
    normalized = code.strip().upper() if isinstance(code, str) else ""
    try:
        return _REGISTRY[normalized]
    except KeyError:
        raise CurrencyNotFoundError(normalized or code) from None


def list_currencies():
    """Копия реестра для справки CLI."""
    return dict(_REGISTRY)
