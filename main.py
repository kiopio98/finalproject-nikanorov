"""Точка входа ValutaTrade Hub."""

from valutatrade_hub.cli.interface import run


def main():
    """Запустить консольный интерфейс."""
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
