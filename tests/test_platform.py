"""Проверки моделей, файлов, сценариев и API без внешних запросов."""

import contextlib
import io
import json
import logging
import math
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from valutatrade_hub.cli.interface import Interface
from valutatrade_hub.core import usecases
from valutatrade_hub.core.currencies import (
    CryptoCurrency,
    Currency,
    FiatCurrency,
    get_currency,
)
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    StorageError,
)
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.rates import cached_rate
from valutatrade_hub.core.utils import utc_now
from valutatrade_hub.infra.database import DatabaseManager, atomic_write
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater


class IsolatedTest(unittest.TestCase):
    """Временное хранилище для каждого сценария."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = patch.dict(
            os.environ,
            {
                "VALUTATRADE_DATA_DIR": str(self.root / "data"),
                "VALUTATRADE_LOG_DIR": str(self.root / "logs"),
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        SettingsLoader().reload()
        self.addCleanup(lambda: SettingsLoader().reload())
        self.addCleanup(self.close_logs)
        self.db = DatabaseManager()

    @staticmethod
    def close_logs():
        for name in ("actions", "parser"):
            logger = logging.getLogger(f"valutatrade.{name}")
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)

    def seed_rates(self, timestamp=None):
        timestamp = timestamp or utc_now()
        with self.db.transaction() as data:
            data["rates.json"] = {
                "pairs": {
                    f"{code}_USD": {
                        "rate": rate,
                        "updated_at": timestamp,
                        "source": "Test",
                    }
                    for code, rate in {
                        "BTC": 50000,
                        "ETH": 2500,
                        "SOL": 100,
                        "EUR": 1.25,
                        "GBP": 1.5,
                        "RUB": 0.01,
                    }.items()
                },
                "last_refresh": timestamp,
            }


class ModelsTest(IsolatedTest):
    def test_password_and_round_trip(self):
        first = User.create(1, " alice ", "abcd")
        second = User.create(2, "bob", "abcd")
        self.assertNotEqual(first.salt, second.salt)
        self.assertNotEqual(first.hashed_password, second.hashed_password)
        self.assertTrue(first.verify_password("abcd"))
        self.assertFalse(first.verify_password("wrong"))
        self.assertNotIn("salt", first.get_user_info())
        self.assertNotIn("hashed_password", first.get_user_info())
        restored = User(**first.to_dict())
        self.assertEqual(restored.registration_date, first.registration_date)
        self.assertTrue(restored.verify_password("abcd"))
        first.change_password("new-password")
        self.assertFalse(first.verify_password("abcd"))
        self.assertTrue(first.verify_password("new-password"))

    def test_user_validation(self):
        for name, password in (("", "abcd"), ("   ", "abcd"), ("alice", "abc")):
            with (
                self.subTest(name=name, password=password),
                self.assertRaises(ValueError),
            ):
                User.create(1, name, password)

    def test_wallet_invalid_values_and_overflow(self):
        wallet = Wallet("btc", 1)
        for value in (-1, 0, "1", True, math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                wallet.deposit(value)
            self.assertEqual(wallet.balance, 1)
        for value in (-1, "1", True, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                wallet.balance = value
        wallet.balance = 1e308
        with self.assertRaises(ValueError):
            wallet.deposit(1e308)
        self.assertEqual(wallet.balance, 1e308)

    def test_wallet_withdraw(self):
        wallet = Wallet("BTC", 0.05)
        with self.assertRaisesRegex(InsufficientFundsError, "доступно 0.05 BTC"):
            wallet.withdraw(0.1)
        wallet.withdraw(0.05)
        self.assertEqual(wallet.balance, 0)
        self.assertIn("BTC", wallet.get_balance_info())

    def test_portfolio_encapsulation_and_value(self):
        user = User.create(1, "alice", "abcd")
        portfolio = Portfolio(1, user=user, rate_provider=lambda a, b: {"rate": 2})
        portfolio.add_currency("eur")
        portfolio.get_wallet("EUR").deposit(3)
        portfolio.wallets.clear()
        self.assertEqual(portfolio.get_total_value(), 6)
        self.assertIs(portfolio.user, user)
        with self.assertRaises(ValueError):
            portfolio.add_currency("EUR")
        with self.assertRaises(AttributeError):
            portfolio.user = user

    def test_currency_hierarchy(self):
        with self.assertRaises(TypeError):
            Currency("A", "AA")
        self.assertIsInstance(get_currency(" eur "), FiatCurrency)
        self.assertIsInstance(get_currency("btc"), CryptoCurrency)
        self.assertIn("Issuing:", get_currency("USD").get_display_info())
        self.assertIn("Algo:", get_currency("BTC").get_display_info())
        for code in ("A", "abcdef", "АБВ", "A B", "123"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                FiatCurrency("test", code, "test")
        with self.assertRaises(CurrencyNotFoundError):
            get_currency("AAA")


class UsecasesTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.user = usecases.register("alice", "abcd")
        self.seed_rates()

    def test_registration_login_empty_portfolio(self):
        self.assertEqual(usecases.get_portfolio(self.user.user_id).wallets, {})
        self.assertEqual(usecases.login("alice", "abcd").user_id, self.user.user_id)
        with self.assertRaisesRegex(ValueError, "уже занято"):
            usecases.register("alice", "abcd")
        with self.assertRaisesRegex(ValueError, "Неверный пароль"):
            usecases.login("alice", "wrong")
        with self.assertRaisesRegex(ValueError, "не найден"):
            usecases.login("nobody", "abcd")
        with self.assertRaisesRegex(ValueError, "не короче"):
            usecases.register("bob", "123")
        self.assertEqual(len(self.db.read("users.json")), 1)

    def test_full_trade_cycle_and_isolation(self):
        other = usecases.register("bob", "abcd")
        buy = usecases.buy(self.user.user_id, "btc", 0.05)
        self.assertEqual(buy["estimate_usd"], 2500)
        result = usecases.sell(self.user.user_id, "BTC", 0.01)
        self.assertAlmostEqual(result["after"], 0.04)
        portfolio = usecases.get_portfolio(self.user.user_id)
        self.assertNotIn("USD", portfolio.wallets)
        self.assertEqual(usecases.get_portfolio(other.user_id).wallets, {})
        self.assertAlmostEqual(portfolio.get_total_value("EUR"), 1600)
        self.assertAlmostEqual(
            usecases.portfolio_report(self.user.user_id)["total"], 2000
        )
        self.assertEqual(len(self.db.read("transactions.json")), 2)

    def test_failed_trade_does_not_modify_files_and_logs_error(self):
        usecases.buy(self.user.user_id, "BTC", 0.01)
        before = self.db.read("portfolios.json")
        with self.assertRaises(InsufficientFundsError):
            usecases.sell(self.user.user_id, "BTC", 1)
        self.assertEqual(self.db.read("portfolios.json"), before)
        self.assertEqual(len(self.db.read("transactions.json")), 1)
        records = [
            json.loads(line)
            for line in (self.root / "logs/actions.log")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual([row["result"] for row in records], ["OK", "ERROR"])
        self.assertEqual(records[-1]["error_type"], "InsufficientFundsError")
        self.assertIn("before", records[0])
        self.assertNotIn("abcd", json.dumps(records))

    def test_bad_amount_unknown_currency_missing_wallet_and_session(self):
        for value in (0, -1, True, "2", math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                usecases.buy(self.user.user_id, "BTC", value)
        with self.assertRaises(CurrencyNotFoundError):
            usecases.buy(self.user.user_id, "AAA", 1)
        with self.assertRaisesRegex(ValueError, "нет кошелька"):
            usecases.sell(self.user.user_id, "BTC", 1)
        with self.assertRaisesRegex(ValueError, "login"):
            usecases.buy(999, "BTC", 1)
        self.assertEqual(self.db.read("transactions.json"), [])

    def test_fresh_cross_inverse_identity_no_network(self):
        with patch("valutatrade_hub.parser_service.updater.update_rates") as update:
            self.assertEqual(usecases.get_rate("EUR", "USD")["rate"], 1.25)
            self.assertEqual(usecases.get_rate("USD", "EUR")["rate"], 0.8)
            self.assertEqual(usecases.get_rate("BTC", "EUR")["rate"], 40000)
            self.assertEqual(usecases.get_rate("BTC", "BTC")["rate"], 1)
            update.assert_not_called()

    def test_stale_refresh_and_no_trade_on_network_failure(self):
        old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        self.seed_rates(old)
        self.assertTrue(usecases.show_rates("BTC")[0]["stale"])
        with patch(
            "valutatrade_hub.parser_service.updater.update_rates",
            side_effect=ApiRequestError("offline"),
        ) as update:
            with self.assertRaises(ApiRequestError):
                usecases.buy(self.user.user_id, "BTC", 1)
            update.assert_called_once()
        self.assertEqual(usecases.get_portfolio(self.user.user_id).wallets, {})
        with patch(
            "valutatrade_hub.parser_service.updater.update_rates",
            side_effect=lambda: self.seed_rates(),
        ):
            self.assertEqual(usecases.get_rate("BTC", "USD")["rate"], 50000)

    def test_cross_ttl_checks_both_legs(self):
        with self.db.transaction() as data:
            data["rates.json"]["pairs"]["EUR_USD"]["updated_at"] = (
                datetime.now(UTC) - timedelta(hours=1)
            ).isoformat()
        result = cached_rate(self.db.read("rates.json"), "BTC", "EUR")
        self.assertTrue(result["stale"])
        self.assertEqual(usecases.show_rates(top=2)[0]["currency"], "BTC")
        self.assertEqual(len(usecases.show_rates(top=2)), 2)
        with self.assertRaises(ValueError):
            usecases.show_rates(top=0)

    def test_cli_cycle_and_recover_after_bad_command(self):
        interface = Interface()
        output = io.StringIO()
        commands = [
            "buy --currency BTC --amount 1",
            "login --username alice --password wrong",
            "login --username alice --password abcd",
            "show-portfolio",
            "buy --currency BTC --amount 0.05",
            "sell --currency BTC --amount 0.01",
            "show-portfolio --base EUR",
            "get-rate --from USD --to BTC",
            "buy --currency BTC --amount nan",
            "sell --currency BTC --amount 100",
            "get-rate --from AAA --to USD",
            'buy --currency "',
            "unknown",
            "buy --help",
            "show-rates --top 2",
            "logout",
        ]
        with contextlib.redirect_stdout(output):
            for command in commands:
                self.assertTrue(interface.execute(command))
            self.assertFalse(interface.execute("exit"))
        text = output.getvalue()
        for expected in (
            "Сначала выполните login",
            "Неверный пароль",
            "пуст",
            "Вы вошли",
            "Покупка выполнена",
            "Продажа выполнена",
            "1600.0000",
            "Недостаточно средств",
            "Неизвестная валюта",
        ):
            self.assertIn(expected, text)


class StorageTest(IsolatedTest):
    def test_singletons_and_defaults(self):
        self.assertIs(SettingsLoader(), SettingsLoader())
        self.assertIs(DatabaseManager(), DatabaseManager())
        self.assertEqual(self.db.read("users.json"), [])
        self.assertEqual(SettingsLoader().get("unknown", 3), 3)

    def test_corrupt_file_preserved(self):
        self.db.directory.mkdir()
        path = self.db.directory / "users.json"
        path.write_text("{invalid", encoding="utf-8")
        with self.assertRaises(StorageError):
            usecases.register("alice", "abcd")
        self.assertEqual(path.read_text(encoding="utf-8"), "{invalid")

    def test_rollback_on_domain_error(self):
        with self.assertRaises(ValueError):
            with self.db.transaction() as data:
                data["users.json"].append({"not": "saved"})
                raise ValueError("abort")
        self.assertEqual(self.db.read("users.json"), [])

    def test_cross_process_lock_not_deleted_by_failed_acquisition(self):
        self.db.directory.mkdir()
        lock = self.db.directory / ".lock"
        lock.write_text("other-process", encoding="utf-8")
        with self.assertRaises(StorageError):
            self.db.read("users.json")
        self.assertTrue(lock.exists())

    def test_interrupted_commit_recovered(self):
        original = atomic_write
        failed = False

        def fail_one_file(path, data):
            nonlocal failed
            if path.name == "portfolios.json" and not failed:
                failed = True
                raise OSError("disk failure")
            original(path, data)

        with patch(
            "valutatrade_hub.infra.database.atomic_write", side_effect=fail_one_file
        ):
            with self.assertRaises(StorageError):
                usecases.register("alice", "abcd")
        self.assertTrue((self.db.directory / ".transaction.json").exists())
        self.assertEqual(len(self.db.read("users.json")), 1)
        self.assertEqual(len(self.db.read("portfolios.json")), 1)
        self.assertFalse((self.db.directory / ".transaction.json").exists())

    def test_atomic_replace_failure_preserves_previous_file(self):
        path = self.root / "value.json"
        atomic_write(path, {"old": 1})
        with patch("valutatrade_hub.infra.database.os.replace", side_effect=OSError):
            with self.assertRaises(OSError):
                atomic_write(path, {"new": 2})
        self.assertEqual(json.loads(path.read_text()), {"old": 1})
        self.assertEqual(list(self.root.glob("*.tmp")), [])


class ApiTest(IsolatedTest):
    def response(self, data, status=200):
        response = Mock(status_code=status)
        response.json.return_value = data
        session = Mock()
        session.get.return_value = response
        return session

    def test_coingecko_mapping_and_timeout(self):
        session = self.response(
            {
                "bitcoin": {"usd": 50000},
                "ethereum": {"usd": 2500},
                "solana": {"usd": 100},
            }
        )
        result = CoinGeckoClient(session=session).fetch_rates()
        self.assertEqual(result, {"BTC_USD": 50000, "ETH_USD": 2500, "SOL_USD": 100})
        self.assertEqual(session.get.call_args.kwargs["timeout"], 10)
        self.assertIn("bitcoin", session.get.call_args.kwargs["params"]["ids"])

    def test_fiat_inversion_keyed_and_open_formats(self):
        for field, key in (("rates", ""), ("conversion_rates", "test-secret-key")):
            with self.subTest(field=field):
                session = self.response(
                    {
                        "result": "success",
                        "base_code": "USD",
                        field: {"EUR": 0.8, "GBP": 0.5, "RUB": 100},
                    }
                )
                client = ExchangeRateApiClient(
                    ParserConfig(EXCHANGERATE_API_KEY=key), session
                )
                rates = client.fetch_rates()
                self.assertEqual(
                    rates, {"EUR_USD": 1.25, "GBP_USD": 2, "RUB_USD": 0.01}
                )
                self.assertEqual(client.meta["open_access"], not bool(key))

    def test_http_and_network_errors_do_not_expose_key(self):
        for status in (401, 403, 429, 500):
            with (
                self.subTest(status=status),
                self.assertRaises(ApiRequestError) as error,
            ):
                ExchangeRateApiClient(
                    ParserConfig(EXCHANGERATE_API_KEY="secret"),
                    self.response({}, status),
                ).fetch_rates()
            self.assertNotIn("secret", str(error.exception))
        for exception in (
            requests.Timeout("secret"),
            requests.ConnectionError("secret"),
        ):
            session = Mock()
            session.get.side_effect = exception
            with self.assertRaises(ApiRequestError) as error:
                CoinGeckoClient(session=session).fetch_rates()
            self.assertNotIn("secret", str(error.exception))

    def test_invalid_json_and_rates(self):
        session = self.response({})
        session.get.return_value.json.side_effect = ValueError("bad")
        with self.assertRaises(ApiRequestError):
            CoinGeckoClient(session=session).fetch_rates()
        for value in (0, -1, True, math.nan, math.inf, "100"):
            session = self.response(
                {
                    "result": "success",
                    "base_code": "USD",
                    "rates": {"EUR": value, "GBP": 1, "RUB": 100},
                }
            )
            with self.subTest(value=value), self.assertRaises(ApiRequestError):
                ExchangeRateApiClient(session=session).fetch_rates()

    def observation(self, timestamp, rate=100):
        return {
            "id": f"BTC_USD_{timestamp}",
            "from_currency": "BTC",
            "to_currency": "USD",
            "rate": rate,
            "timestamp": timestamp,
            "source": "Test",
            "meta": {},
        }

    def test_history_dedup_and_newest_wins(self):
        storage = RatesStorage(self.db)
        new = self.observation(utc_now(), 200)
        old = self.observation(
            (datetime.now(UTC) - timedelta(hours=1)).isoformat(), 100
        )
        self.assertEqual(storage.save([new]), 1)
        self.assertEqual(storage.save([old, new]), 0)
        self.assertEqual(len(self.db.read("exchange_rates.json")), 2)
        self.assertEqual(self.db.read("rates.json")["pairs"]["BTC_USD"]["rate"], 200)

    def test_partial_failure_preserves_other_pairs(self):
        self.seed_rates()
        good = Mock(source="Good", meta={})
        good.fetch_rates.return_value = {"BTC_USD": 60000}
        bad = Mock(source="Bad")
        bad.fetch_rates.side_effect = ApiRequestError("offline")
        result = RatesUpdater([bad, good]).run_update()
        self.assertEqual(result["updated"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(self.db.read("rates.json")["pairs"]["EUR_USD"]["rate"], 1.25)
        self.assertEqual(self.db.read("rates.json")["pairs"]["BTC_USD"]["rate"], 60000)
        before = self.db.read("rates.json")
        with self.assertRaises(ApiRequestError):
            RatesUpdater([bad]).run_update()
        self.assertEqual(self.db.read("rates.json"), before)


if __name__ == "__main__":
    unittest.main()
