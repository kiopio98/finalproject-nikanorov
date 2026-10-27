"""Необязательный запуск парсера с интервалом, без фоновой установки."""

import argparse
import time

from valutatrade_hub.core.exceptions import ValutaTradeError
from valutatrade_hub.logging_config import get_logger
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.updater import update_rates


def run_scheduler(interval=None, *, once=False, source=None):
    """Выполнять обновления до Ctrl+C; интервал не меньше 1 часа."""
    interval = interval or ParserConfig().UPDATE_INTERVAL
    if interval < 3600:
        raise ValueError("Интервал должен быть не меньше 3600 секунд")
    try:
        while True:
            try:
                update_rates(source)
            except ValutaTradeError as error:
                get_logger("parser").warning("%s", error)
            if once:
                return
            time.sleep(interval)
    except KeyboardInterrupt:
        return


def main():
    """Параметры самостоятельного Parser Service."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=3600)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--source", choices=("coingecko", "exchangerate"))
    args = parser.parse_args()
    run_scheduler(args.interval, once=args.once, source=args.source)


if __name__ == "__main__":
    main()
