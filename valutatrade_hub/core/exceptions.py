"""Ожидаемые ошибки предметной области."""


class ValutaTradeError(Exception):
    """Базовая ошибка, которую можно показать пользователю."""


class InsufficientFundsError(ValutaTradeError):
    """На кошельке недостаточно единиц продаваемой валюты."""

    def __init__(self, available, required, code):
        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {available:g} {code}, "
            f"требуется {required:g} {code}"
        )


class CurrencyNotFoundError(ValutaTradeError):
    """Код отсутствует в реестре валют."""

    def __init__(self, code):
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(ValutaTradeError):
    """Источник курсов недоступен или вернул некорректный ответ."""

    def __init__(self, reason):
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")


class StorageError(ValutaTradeError):
    """Файл недоступен или повреждён; его нельзя молча заменить."""
