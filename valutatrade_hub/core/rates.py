"""Чтение снимка, TTL, обратные курсы и кросс-курсы через USD."""

from datetime import UTC, datetime

from valutatrade_hub.core.currencies import CryptoCurrency, get_currency
from valutatrade_hub.core.exceptions import ApiRequestError, StorageError
from valutatrade_hub.core.utils import parse_time, utc_now, valid_number
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


def cached_rate(snapshot, from_code, to_code):
    """Вернуть курс и метаданные либо None, если необходимых пар нет."""
    if from_code == to_code:
        return {
            "rate": 1.0,
            "updated_at": utc_now(),
            "source": "identity",
            "stale": False,
        }
    try:
        pairs = snapshot["pairs"]
        entries = [
            pairs[f"{code}_USD"] for code in (from_code, to_code) if code != "USD"
        ]
        source_rate = (
            1.0
            if from_code == "USD"
            else valid_number(pairs[f"{from_code}_USD"]["rate"])
        )
        target_rate = (
            1.0 if to_code == "USD" else valid_number(pairs[f"{to_code}_USD"]["rate"])
        )
        dates = [parse_time(entry["updated_at"]) for entry in entries]
        ttl = SettingsLoader().get("RATES_TTL_SECONDS")
        now = datetime.now(UTC)
        stale = any(not 0 <= (now - date).total_seconds() <= ttl for date in dates)
        oldest = min(entries, key=lambda entry: parse_time(entry["updated_at"]))
        return {
            "rate": valid_number(source_rate / target_rate),
            "updated_at": oldest["updated_at"],
            "source": ", ".join(sorted({entry["source"] for entry in entries})),
            "stale": stale,
        }
    except KeyError:
        return None
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise StorageError("Повреждён формат курса в rates.json") from error


def get_rate(from_code, to_code):
    """Использовать свежий снимок; при необходимости один раз вызвать парсер."""
    source = get_currency(from_code).code
    target = get_currency(to_code).code
    database = DatabaseManager()
    result = cached_rate(database.read("rates.json"), source, target)
    if result is not None and not result["stale"]:
        return result
    from valutatrade_hub.parser_service.updater import update_rates

    try:
        update_rates()
    except ApiRequestError:
        raise ApiRequestError(
            f"Курс {source}→{target} недоступен или устарел. "
            "Выполните update-rates и повторите попытку позже"
        ) from None
    result = cached_rate(database.read("rates.json"), source, target)
    if result is None or result["stale"]:
        raise ApiRequestError(
            f"Курс {source}→{target} недоступен. Повторите попытку позже"
        )
    return result


def show_rates(currency=None, top=None, base="USD"):
    """Показать только локальные данные, помечая устаревшие."""
    base = get_currency(base).code
    code_filter = get_currency(currency).code if currency else None
    if top is not None and (
        isinstance(top, bool) or not isinstance(top, int) or top < 1
    ):
        raise ValueError("--top должен быть положительным целым числом")
    snapshot = DatabaseManager().read("rates.json")
    if not snapshot.get("pairs"):
        raise ValueError("Локальный кеш курсов пуст. Выполните 'update-rates'")
    rows = []
    for pair in snapshot["pairs"]:
        code = pair.split("_")[0]
        if code_filter and code != code_filter:
            continue
        currency_model = get_currency(code)
        if top and not isinstance(currency_model, CryptoCurrency):
            continue
        result = cached_rate(snapshot, code, base)
        if result:
            rows.append({"currency": code, "base": base, **result})
    if not rows:
        raise ValueError("Подходящие курсы не найдены в кеше; выполните update-rates")
    rows.sort(key=(lambda row: -row["rate"]) if top else lambda row: row["currency"])
    return rows[:top] if top else rows
