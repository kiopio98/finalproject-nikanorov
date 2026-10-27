"""Координация независимых API-источников."""

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import utc_now, valid_number
from valutatrade_hub.logging_config import get_logger
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.storage import RatesStorage


class RatesUpdater:
    """Сбой одного источника не уничтожает данные остальных."""

    def __init__(self, clients=None, storage=None):
        self.clients = (
            clients
            if clients is not None
            else [CoinGeckoClient(), ExchangeRateApiClient()]
        )
        self.storage = storage or RatesStorage()

    def run_update(self):
        """Получить, объединить и сохранить курсы с метаданными."""
        logger = get_logger("parser")
        logger.info("Starting rates update")
        observations, errors = [], []
        for client in self.clients:
            logger.info("Fetching from %s", client.source)
            try:
                rates = client.fetch_rates()
                timestamp = utc_now()
                batch = []
                for pair, rate in rates.items():
                    source, target = pair.split("_")
                    meta = dict(getattr(client, "meta", {}))
                    raw_ids = meta.pop("raw_ids", {})
                    if raw_ids:
                        meta["raw_id"] = raw_ids[source]
                    batch.append(
                        {
                            "id": f"{pair}_{timestamp}",
                            "from_currency": source,
                            "to_currency": target,
                            "rate": valid_number(rate),
                            "timestamp": timestamp,
                            "source": client.source,
                            "meta": meta,
                        }
                    )
                observations.extend(batch)
                logger.info("%s: OK (%d rates)", client.source, len(batch))
            except ApiRequestError as error:
                errors.append(str(error))
                logger.warning("%s", error)
        if not observations:
            raise ApiRequestError("; ".join(errors) or "источники не вернули курсы")
        updated = self.storage.save(observations)
        logger.info("Update complete: %d pairs; %d errors", updated, len(errors))
        return {
            "updated": updated,
            "errors": errors,
            "last_refresh": max(item["timestamp"] for item in observations),
        }


def update_rates(source=None):
    """Обновить все источники или только выбранный."""
    factories = {"coingecko": CoinGeckoClient, "exchangerate": ExchangeRateApiClient}
    if source is not None and source not in factories:
        raise ValueError("Источник: coingecko или exchangerate")
    clients = [factories[source]()] if source else None
    return RatesUpdater(clients).run_update()
