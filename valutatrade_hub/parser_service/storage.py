"""Сохранение истории и актуального снимка под общей транзакцией."""

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.utils import parse_time, valid_number
from valutatrade_hub.infra.database import DatabaseManager


class RatesStorage:
    """Более старые наблюдения не заменяют новый курс."""

    def __init__(self, database=None):
        self.database = database or DatabaseManager()

    def save(self, observations):
        """Добавить уникальные наблюдения и вернуть число обновлённых пар."""
        for item in observations:
            get_currency(item["from_currency"])
            if item["to_currency"] != "USD":
                raise ValueError("В снимке поддерживается базовая валюта USD")
            valid_number(item["rate"])
            parse_time(item["timestamp"])
        updated = 0
        with self.database.transaction() as data:
            snapshot = data["rates.json"]
            history = data["exchange_rates.json"]
            if not isinstance(snapshot.get("pairs"), dict):
                raise StorageError("Повреждён формат rates.json")
            try:
                known_ids = {item["id"] for item in history}
                for item in observations:
                    if item["id"] not in known_ids:
                        history.append(item)
                        known_ids.add(item["id"])
                    pair = f"{item['from_currency']}_{item['to_currency']}"
                    current = snapshot["pairs"].get(pair)
                    if current and parse_time(current["updated_at"]) >= parse_time(
                        item["timestamp"]
                    ):
                        continue
                    snapshot["pairs"][pair] = {
                        "rate": item["rate"],
                        "updated_at": item["timestamp"],
                        "source": item["source"],
                    }
                    updated += 1
                if updated:
                    snapshot["last_refresh"] = max(
                        (entry["updated_at"] for entry in snapshot["pairs"].values()),
                        key=parse_time,
                    )
            except (KeyError, TypeError, ValueError) as error:
                raise StorageError("Повреждён снимок или история курсов") from error
        return updated
