"""Разбор команд и вывод результатов; расчёты выполняются в core."""

import argparse
import getpass
import shlex
import sys

from prettytable import PrettyTable

from valutatrade_hub.core import usecases
from valutatrade_hub.core.currencies import list_currencies
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    StorageError,
)
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.updater import update_rates


class CommandParser(argparse.ArgumentParser):
    """Ошибки argparse не должны завершать интерактивную сессию."""

    def error(self, message):
        """Передать ошибку единому обработчику интерфейса."""
        raise ValueError(message)


def create_parser():
    """Определить доступные команды и их аргументы."""
    parser = CommandParser(prog="project", description="ValutaTrade Hub")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("register", "login"):
        command = commands.add_parser(
            name, help="Регистрация" if name == "register" else "Вход в аккаунт"
        )
        command.add_argument("--username", required=True)
        command.add_argument("--password", help="Без флага — скрытый ввод пароля")
    portfolio = commands.add_parser("show-portfolio", help="Портфель и общая оценка")
    portfolio.add_argument("--base", default=None)
    for name in ("buy", "sell"):
        command = commands.add_parser(name, help="Виртуальная сделка")
        command.add_argument("--currency", required=True)
        command.add_argument("--amount", required=True, type=float)
    rate = commands.add_parser("get-rate", help="Актуальный курс пары")
    rate.add_argument("--from", dest="from_code", required=True)
    rate.add_argument("--to", dest="to_code", required=True)
    update = commands.add_parser("update-rates", help="Обновить курсы через API")
    update.add_argument("--source", choices=("coingecko", "exchangerate"))
    rates = commands.add_parser("show-rates", help="Просмотреть локальный кеш")
    rates.add_argument("--currency")
    rates.add_argument("--top", type=int)
    rates.add_argument("--base", default=None)
    for name, help_text in (
        ("currencies", "Список валют"),
        ("logout", "Выйти из аккаунта"),
        ("help", "Справка"),
        ("exit", "Завершить программу"),
    ):
        commands.add_parser(name, help=help_text)
    return parser


class Interface:
    """Пользовательская сессия существует только в памяти процесса."""

    def __init__(self):
        self.current_user = None
        self.parser = create_parser()
        self.last_error = False

    def _require_login(self):
        if self.current_user is None:
            raise ValueError("Сначала выполните login")
        return self.current_user.user_id

    @staticmethod
    def _password(args):
        if args.password is not None:
            return args.password
        if not sys.stdin.isatty():
            raise ValueError("Для неинтерактивного ввода укажите --password")
        return getpass.getpass("Пароль: ")

    def execute(self, line):
        """Обработать одну строку; False означает завершение сеанса."""
        self.last_error = False
        if not line.strip():
            return True
        try:
            args = self.parser.parse_args(shlex.split(line))
            return self._dispatch(args)
        except SystemExit as error:
            # --help печатает справку и выходит только из разбора одной команды.
            if error.code:
                self.last_error = True
                print("Не удалось разобрать команду. Введите help")
        except InsufficientFundsError as error:
            self.last_error = True
            print(error)
        except CurrencyNotFoundError as error:
            self.last_error = True
            print(f"{error}. Доступные коды: {', '.join(list_currencies())}")
        except ApiRequestError as error:
            self.last_error = True
            print(f"{error}. Проверьте подключение и повторите update-rates позже")
        except (ValueError, StorageError) as error:
            self.last_error = True
            print(error)
        return True

    def _dispatch(self, args):
        command = args.command
        if command == "exit":
            return False
        if command == "help":
            self.parser.print_help()
        elif command == "register":
            user = usecases.register(args.username, self._password(args))
            print(
                f"Пользователь '{user.username}' зарегистрирован (id={user.user_id}). "
                f"Войдите: login --username {shlex.quote(user.username)}"
            )
        elif command == "login":
            user = usecases.login(args.username, self._password(args))
            self.current_user = user
            print(f"Вы вошли как '{user.username}'")
        elif command == "logout":
            self.current_user = None
            print("Вы вышли из аккаунта")
        elif command == "show-portfolio":
            base = args.base or SettingsLoader().get("DEFAULT_BASE_CURRENCY")
            report = usecases.portfolio_report(self._require_login(), base)
            if not report["rows"]:
                print("Ваш портфель пуст. Выполните buy, чтобы добавить валюту")
            else:
                table = PrettyTable(
                    ["Валюта", "Баланс", f"Стоимость, {report['base']}"]
                )
                for row in report["rows"]:
                    table.add_row(
                        [
                            row["currency"],
                            f"{row['balance']:.8f}",
                            f"{row['value']:.4f}",
                        ]
                    )
                print(f"Портфель пользователя '{report['username']}'")
                print(table)
                print(f"ИТОГО: {report['total']:.4f} {report['base']}")
        elif command in ("buy", "sell"):
            function = usecases.buy if command == "buy" else usecases.sell
            result = function(self._require_login(), args.currency, args.amount)
            label = "Покупка" if command == "buy" else "Продажа"
            print(f"{label} выполнена: {result['amount']:.4f} {result['currency']}")
            print(f"Баланс: {result['before']:.4f} → {result['after']:.4f}")
            print(
                f"Курс: {result['rate']:.8f} USD; "
                f"оценочная стоимость: {result['estimate_usd']:.2f} USD"
            )
        elif command == "get-rate":
            result = usecases.get_rate(args.from_code, args.to_code)
            pair = f"{args.from_code.strip().upper()}→{args.to_code.strip().upper()}"
            print(
                f"Курс {pair}: {result['rate']:.10g} (обновлён: {result['updated_at']})"
            )
        elif command == "update-rates":
            print("Обновление курсов...")
            result = update_rates(args.source)
            print(
                f"Обновлено пар: {result['updated']}. Время: {result['last_refresh']}"
            )
            for error in result["errors"]:
                print(f"Источник недоступен: {error}")
            print("Rates By Exchange Rate API: https://www.exchangerate-api.com")
        elif command == "show-rates":
            base = args.base or SettingsLoader().get("DEFAULT_BASE_CURRENCY")
            rows = usecases.show_rates(args.currency, args.top, base)
            table = PrettyTable(["Пара", "Курс", "Обновлено (UTC)", "Состояние"])
            for row in rows:
                table.add_row(
                    [
                        f"{row['currency']}_{row['base']}",
                        f"{row['rate']:.10g}",
                        row["updated_at"],
                        "устарел" if row["stale"] else "актуален",
                    ]
                )
            print(table)
            if any(row["stale"] for row in rows):
                print("Есть устаревшие курсы. Выполните update-rates")
            print("Rates By Exchange Rate API: https://www.exchangerate-api.com")
        elif command == "currencies":
            for currency in list_currencies().values():
                print(currency.get_display_info())
        return True


def run(argv=None):
    """Запустить REPL или одну команду, переданную после имени приложения."""
    interface = Interface()
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        interface.execute(shlex.join(argv))
        return int(interface.last_error)
    print("ValutaTrade Hub — виртуальная торговля. Введите help для списка команд.")
    try:
        while True:
            try:
                line = input("valuta> ")
            except EOFError:
                break
            if not interface.execute(line):
                break
    except KeyboardInterrupt:
        print("\nСеанс завершён")
    return 0
