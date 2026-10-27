"""Общая проверка чисел и времени."""

import math
from datetime import UTC, datetime


def valid_number(value, *, positive=True):
    """Вернуть конечное число; bool, строки, NaN и бесконечность запрещены."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Сумма должна быть числом")
    number = float(value)
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        sign = "положительной" if positive else "неотрицательной"
        raise ValueError(f"Сумма должна быть конечной и {sign}")
    return number


def utc_now():
    """Текущее время UTC с микросекундами для уникальности наблюдений."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value):
    """Прочитать ISO-время с обязательным часовым поясом."""
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Время должно содержать часовой пояс")
    return result.astimezone(UTC)
