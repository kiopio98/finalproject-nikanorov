"""Регистрация, авторизация, портфель и виртуальные сделки."""

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError, StorageError
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.rates import get_rate, show_rates
from valutatrade_hub.core.utils import utc_now, valid_number
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager

__all__ = [
    "register",
    "login",
    "get_user",
    "get_portfolio",
    "buy",
    "sell",
    "get_rate",
    "show_rates",
    "portfolio_report",
]


def _users(rows):
    try:
        users = [User(**row) for row in rows]
        if len({user.user_id for user in users}) != len(users):
            raise ValueError("Повторяющиеся id")
        if len({user.username for user in users}) != len(users):
            raise ValueError("Повторяющиеся имена")
        return users
    except (TypeError, ValueError) as error:
        raise StorageError("Повреждены записи users.json") from error


def _find_user(rows, user_id):
    for user in _users(rows):
        if user.user_id == user_id:
            return user
    raise ValueError("Сначала выполните login")


def register(username: str, password: str):
    """Создать пользователя и пустой портфель одной транзакцией."""
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Имя пользователя не может быть пустым")
    username = username.strip()
    with DatabaseManager().transaction() as data:
        users = _users(data["users.json"])
        if any(user.username == username for user in users):
            raise ValueError(f"Имя пользователя '{username}' уже занято")
        user_id = max((user.user_id for user in users), default=0) + 1
        user = User.create(user_id, username, password)
        data["users.json"].append(user.to_dict())
        data["portfolios.json"].append({"user_id": user_id, "wallets": {}})
    return user


def login(username: str, password: str):
    """Проверить имя и пароль, вернуть пользователя для сессии CLI."""
    username = username.strip()
    for user in _users(DatabaseManager().read("users.json")):
        if user.username == username:
            if not user.verify_password(password):
                raise ValueError("Неверный пароль")
            return user
    raise ValueError(f"Пользователь '{username}' не найден")


def get_user(user_id: int):
    """Загрузить владельца портфеля."""
    return _find_user(DatabaseManager().read("users.json"), user_id)


def _portfolio(rows, user):
    try:
        matches = [row for row in rows if row["user_id"] == user.user_id]
        if len(matches) != 1:
            raise ValueError("Отсутствует или продублирован портфель")
        row = matches[0]
        wallets = {
            code: Wallet(code, item["balance"]) for code, item in row["wallets"].items()
        }
        return Portfolio(user.user_id, wallets, user=user)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise StorageError("Повреждены записи portfolios.json") from error


def get_portfolio(user_id: int):
    """Прочитать пользователя и его кошельки в одном снимке."""
    with DatabaseManager().transaction() as data:
        return _portfolio(
            data["portfolios.json"], _find_user(data["users.json"], user_id)
        )


def portfolio_report(user_id, base="USD"):
    """Подготовить строки и общую стоимость для CLI."""
    base = get_currency(base).code
    portfolio = get_portfolio(user_id)
    rows = []
    for code, wallet in sorted(portfolio.wallets.items()):
        rate = get_rate(code, base)["rate"] if wallet.balance else 0.0
        rows.append(
            {
                "currency": code,
                "balance": wallet.balance,
                "value": valid_number(wallet.balance * rate, positive=False),
            }
        )
    total = valid_number(sum(row["value"] for row in rows), positive=False)
    return {
        "username": portfolio.user.username,
        "base": base,
        "rows": rows,
        "total": total,
    }


def _trade(user_id, currency_code, amount, *, selling):
    get_user(user_id)  # Нет сетевого обращения до проверки входа.
    code = get_currency(currency_code).code
    amount = valid_number(amount)
    if selling:
        wallet = get_portfolio(user_id).get_wallet(code)
        if amount > wallet.balance:
            raise InsufficientFundsError(wallet.balance, amount, code)
    # Сетевой запрос выполняется до блокировки файлов. Ошибка не меняет баланс.
    quote = get_rate(code, "USD")
    estimate = valid_number(amount * quote["rate"])
    with DatabaseManager().transaction() as data:
        user = _find_user(data["users.json"], user_id)
        portfolio = _portfolio(data["portfolios.json"], user)
        if not selling and code not in portfolio.wallets:
            portfolio.add_currency(code)
        wallet = portfolio.get_wallet(code)
        before = wallet.balance
        if selling:
            wallet.withdraw(amount)
        else:
            wallet.deposit(amount)
        result = {
            "user_id": user_id,
            "username": user.username,
            "currency": code,
            "amount": amount,
            "rate": quote["rate"],
            "before": before,
            "after": wallet.balance,
            "estimate_usd": estimate,
            "action": "SELL" if selling else "BUY",
            "timestamp": utc_now(),
        }
        for index, row in enumerate(data["portfolios.json"]):
            if row["user_id"] == user_id:
                data["portfolios.json"][index] = portfolio.to_dict()
                break
        data["transactions.json"].append(result)
    return result


@log_action("BUY", verbose=True)
def buy(user_id: int, currency_code: str, amount: float):
    """Увеличить целевой кошелёк без списания USD (упрощённая модель)."""
    return _trade(user_id, currency_code, amount, selling=False)


@log_action("SELL", verbose=True)
def sell(user_id: int, currency_code: str, amount: float):
    """Уменьшить целевой кошелёк без зачисления USD."""
    return _trade(user_id, currency_code, amount, selling=True)
