"""JSON-хранилище с блокировкой и атомарной заменой файлов."""

import copy
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.infra.settings import SettingsLoader

DEFAULTS = {
    "users.json": [],
    "portfolios.json": [],
    "transactions.json": [],
    "rates.json": {"pairs": {}, "last_refresh": None},
    "exchange_rates.json": [],
}


def atomic_write(path: Path, data):
    """Записать UTF-8 JSON через временный файл в том же каталоге."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class DatabaseManager:
    """Singleton: один шлюз к данным и одна блокировка внутри процесса."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._mutex = threading.RLock()
            cls._instance = instance
        return cls._instance

    @property
    def directory(self):
        """Актуальный путь из настроек, без привязки к месту установки wheel."""
        return SettingsLoader().get("DATA_DIR")

    def _read(self, name):
        path = self.directory / name
        if not path.exists():
            return copy.deepcopy(DEFAULTS[name])
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, type(DEFAULTS[name])):
            raise StorageError(f"Неверный формат {name}")
        return data

    def _recover(self):
        journal = self.directory / ".transaction.json"
        if journal.exists():
            with journal.open(encoding="utf-8") as file:
                pending = json.load(file)
            if not isinstance(pending, dict) or not set(pending) <= DEFAULTS.keys():
                raise StorageError("Повреждён журнал транзакции")
            for name, value in pending.items():
                atomic_write(self.directory / name, value)
            journal.unlink()

    @contextmanager
    def transaction(self):
        """Read-modify-write под блокировкой; исключение отменяет изменения.

        Журнал перед заменой файлов позволяет завершить прерванную запись при
        следующем обращении. При ошибке диска результат требует перечитывания.
        """
        with self._mutex:
            lock = None
            acquired = False
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                lock = self.directory / ".lock"
                try:
                    with lock.open("x", encoding="utf-8") as file:
                        file.write(str(os.getpid()))
                    acquired = True
                except FileExistsError:
                    raise StorageError(
                        "Хранилище занято. Закройте другой экземпляр приложения. "
                        "После аварийного завершения проверьте data/.lock"
                    ) from None
                self._recover()
                before = {name: self._read(name) for name in DEFAULTS}
                data = copy.deepcopy(before)
                yield data
                changed = {
                    name: value for name, value in data.items() if value != before[name]
                }
                if changed:
                    atomic_write(self.directory / ".transaction.json", changed)
                    for name, value in changed.items():
                        atomic_write(self.directory / name, value)
                    (self.directory / ".transaction.json").unlink()
            except (OSError, json.JSONDecodeError, UnicodeError) as error:
                raise StorageError(
                    "Не удалось прочитать или сохранить JSON. "
                    "Проверьте файлы, права и свободное место; "
                    "после сбоя записи перечитайте состояние перед повтором"
                ) from error
            finally:
                if acquired and lock is not None:
                    lock.unlink(missing_ok=True)

    def read(self, name):
        """Прочитать независимую копию файла под общей блокировкой."""
        if name not in DEFAULTS:
            raise ValueError("Неизвестный файл хранилища")
        with self.transaction() as data:
            return copy.deepcopy(data[name])
