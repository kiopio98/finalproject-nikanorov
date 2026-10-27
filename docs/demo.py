"""Воспроизводимый пример CLI с учебными HTTP-ответами, без сети."""

import json
import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from valutatrade_hub.cli.interface import Interface
from valutatrade_hub.infra.settings import SettingsLoader


class DemoResponse:
    """Минимальный HTTP-ответ для двух форматов API."""

    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        """Независимая копия учебного ответа."""
        return json.loads(json.dumps(self.data))


def demo_get(url, **kwargs):
    """Подменить только HTTP-границу; остальная логика выполняется как обычно."""
    if "coingecko" in url:
        return DemoResponse(
            {
                "bitcoin": {"usd": 50000},
                "ethereum": {"usd": 2500},
                "solana": {"usd": 100},
            }
        )
    return DemoResponse(
        {
            "result": "success",
            "base_code": "USD",
            "rates": {"EUR": 0.8, "GBP": 0.5, "RUB": 100},
        }
    )


def main():
    """Полный цикл и ошибки на временных данных."""
    print("ДЕМОНСТРАЦИЯ: учебные HTTP-ответы, реальные команды приложения.", flush=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with (
            patch.dict(
                os.environ,
                {
                    "VALUTATRADE_DATA_DIR": str(root / "data"),
                    "VALUTATRADE_LOG_DIR": str(root / "logs"),
                },
            ),
            patch("valutatrade_hub.parser_service.api_clients.requests.get", demo_get),
        ):
            SettingsLoader().reload()
            interface = Interface()
            commands = [
                "register --username alice --password demo123",
                "login --username alice --password wrong",
                "login --username alice --password demo123",
                "show-portfolio",
                "update-rates",
                "show-rates --top 2",
                "show-rates --currency RUB",
                "buy --currency BTC --amount 0.05",
                "sell --currency BTC --amount 0.01",
                "show-portfolio --base EUR",
                "get-rate --from USD --to BTC",
                "sell --currency BTC --amount 100",
                "get-rate --from AAA --to USD",
                "buy --currency BTC --amount nan",
                "exit",
            ]
            for command in commands:
                print(f"valuta> {command}", flush=True)
                if not interface.execute(command):
                    break
            for name in ("actions", "parser"):
                logger = logging.getLogger(f"valutatrade.{name}")
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)
    SettingsLoader().reload()


if __name__ == "__main__":
    main()
