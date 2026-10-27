"""Пользователь, кошелёк и портфель."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import parse_time, valid_number


class User:
    """Учётная запись с индивидуальной солью и SHA-256 пароля."""

    def __init__(self, user_id, username, hashed_password, salt, registration_date):
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise ValueError("Некорректный id пользователя")
        self.__user_id = user_id
        self.username = username
        if (
            not isinstance(hashed_password, str)
            or len(hashed_password) != 64
            or any(c not in "0123456789abcdef" for c in hashed_password)
        ):
            raise ValueError("Некорректный хеш пароля")
        if not isinstance(salt, str) or not salt:
            raise ValueError("Соль не может быть пустой")
        self.__hashed_password = hashed_password
        self.__salt = salt
        if isinstance(registration_date, str):
            registration_date = parse_time(registration_date)
        if not isinstance(registration_date, datetime) or not registration_date.tzinfo:
            raise ValueError("Некорректная дата регистрации")
        self.__registration_date = registration_date.astimezone(UTC)

    @classmethod
    def create(cls, user_id, username, password):
        """Создать аккаунт, не сохраняя исходный пароль."""
        cls._validate_password(password)
        salt = secrets.token_hex(16)
        return cls(
            user_id, username, cls._hash(password, salt), salt, datetime.now(UTC)
        )

    @staticmethod
    def _hash(password, salt):
        return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_password(password):
        if not isinstance(password, str) or len(password) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")

    @property
    def user_id(self):
        """Неизменяемый идентификатор."""
        return self.__user_id

    @property
    def username(self):
        """Имя для входа."""
        return self.__username

    @username.setter
    def username(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым")
        self.__username = value.strip()

    @property
    def hashed_password(self):
        """Хеш для сохранения в локальном хранилище."""
        return self.__hashed_password

    @property
    def salt(self):
        """Соль для сериализации учётной записи."""
        return self.__salt

    @property
    def registration_date(self):
        """Дата регистрации UTC."""
        return self.__registration_date

    def get_user_info(self):
        """Публичные сведения без хеша и соли."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "registration_date": self.registration_date.isoformat(),
        }

    def to_dict(self):
        """Запись для users.json; не предназначена для журналирования."""
        return {
            **self.get_user_info(),
            "hashed_password": self.hashed_password,
            "salt": self.salt,
        }

    def change_password(self, new_password: str):
        """Проверить новый пароль и заменить также соль."""
        self._validate_password(new_password)
        self.__salt = secrets.token_hex(16)
        self.__hashed_password = self._hash(new_password, self.salt)

    def verify_password(self, password: str):
        """Сравнить хеши без сохранения проверяемого пароля."""
        return isinstance(password, str) and hmac.compare_digest(
            self._hash(password, self.salt), self.hashed_password
        )


class Wallet:
    """Остаток в единицах одной валюты."""

    def __init__(self, currency_code: str, balance: float = 0.0):
        self._currency_code = get_currency(currency_code).code
        self.balance = balance

    @property
    def currency_code(self):
        """Код валюты кошелька."""
        return self._currency_code

    @property
    def balance(self):
        """Неотрицательный конечный остаток."""
        return self._balance

    @balance.setter
    def balance(self, value):
        self._balance = valid_number(value, positive=False)

    def deposit(self, amount: float):
        """Зачислить положительное количество единиц валюты."""
        self.balance = self.balance + valid_number(amount)

    def withdraw(self, amount: float):
        """Списать сумму, если хватает остатка."""
        amount = valid_number(amount)
        if amount > self.balance:
            raise InsufficientFundsError(self.balance, amount, self.currency_code)
        self.balance = self.balance - amount

    def get_balance_info(self):
        """Читаемое представление остатка."""
        return f"{self.currency_code}: {self.balance:.4f}"


class Portfolio:
    """Кошельки пользователя и их оценочная стоимость."""

    def __init__(self, user_id: int, wallets=None, *, user=None, rate_provider=None):
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise ValueError("Некорректный id владельца портфеля")
        self.__user_id = user_id
        self.__wallets = {}
        for code, wallet in (wallets or {}).items():
            if not isinstance(wallet, Wallet) or get_currency(code).code != code:
                raise ValueError("Некорректный кошелёк")
            if wallet.currency_code != code:
                raise ValueError("Код кошелька не совпадает с ключом")
            self.__wallets[code] = wallet
        if user is not None and user.user_id != user_id:
            raise ValueError("Пользователь не соответствует портфелю")
        self.__user = user
        self._rate_provider = rate_provider

    @property
    def user_id(self):
        """Владелец портфеля."""
        return self.__user_id

    @property
    def user(self):
        """Объект владельца, доступный только для чтения."""
        if self.__user is None:
            from valutatrade_hub.core.usecases import get_user

            self.__user = get_user(self.user_id)
        return self.__user

    @property
    def wallets(self):
        """Копия словаря: внешний код не может удалить кошелёк из портфеля."""
        return dict(self.__wallets)

    def add_currency(self, currency_code):
        """Добавить отсутствующий кошелёк; существующий не обнуляется."""
        code = get_currency(currency_code).code
        if code in self.__wallets:
            raise ValueError(f"Кошелёк '{code}' уже существует")
        self.__wallets[code] = Wallet(code)

    def get_wallet(self, currency_code) -> Wallet:
        """Найти кошелёк по нормализованному коду."""
        code = get_currency(currency_code).code
        if code not in self.__wallets:
            raise ValueError(f"У вас нет кошелька '{code}'. Добавьте его покупкой")
        return self.__wallets[code]

    def get_total_value(self, base_currency="USD") -> float:
        """Оценить все ненулевые кошельки по актуальным курсам."""
        from valutatrade_hub.core.usecases import get_rate

        base = get_currency(base_currency).code
        provider = self._rate_provider or get_rate
        return valid_number(
            sum(
                valid_number(
                    wallet.balance * provider(code, base)["rate"], positive=False
                )
                for code, wallet in self.__wallets.items()
                if wallet.balance
            ),
            positive=False,
        )

    def to_dict(self):
        """Формат portfolios.json."""
        return {
            "user_id": self.user_id,
            "wallets": {
                code: {"balance": wallet.balance}
                for code, wallet in self.__wallets.items()
            },
        }
