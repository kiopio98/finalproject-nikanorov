# ValutaTrade Hub

Итоговый проект по программированию на Python. Консольная платформа для
отслеживания курсов и симуляции торговли фиатными и криптовалютами.

## Установка и запуск

Нужны Python 3.12+ и [uv](https://docs.astral.sh/uv/getting-started/installation/).

```console
git clone https://github.com/kiopio98/finalproject-nikanorov.git
cd finalproject-nikanorov
uv sync --locked
uv run project
```

Также можно запустить `uv run main.py`. Команды регистрации, входа и сделок
вводятся в одном сеансе: вход не сохраняется после выхода из программы.
Пароль можно не указывать в команде — программа запросит его скрытым вводом.
Для записи демонстрации используются только вымышленные учётные данные.

## Команды

```text
register --username alice --password demo123
login --username alice --password demo123
update-rates
update-rates --source coingecko
update-rates --source exchangerate
show-rates
show-rates --currency BTC
show-rates --top 2
show-rates --base EUR
get-rate --from USD --to BTC
buy --currency BTC --amount 0.05
sell --currency BTC --amount 0.01
show-portfolio
show-portfolio --base EUR
currencies
logout
help
exit
```

Поддерживаются USD, EUR, GBP, RUB, BTC, ETH и SOL. Коды при вводе переводятся
в верхний регистр. Сумма сделки задаётся в единицах выбранной валюты.
Отрицательные суммы, ноль, NaN, бесконечность и продажа сверх остатка запрещены.
Неудачная операция не меняет портфель. Имена пользователей уникальны и
чувствительны к регистру. Минимальная длина пароля — четыре символа.

## Модель сделок

Выбрана **упрощённая модель**, разрешённая в уточнении преподавателя от 25 октября:
`buy` увеличивает остаток выбранной валюты, `sell` уменьшает его. USD не
списываются и не начисляются; выводимая сумма в USD — оценочная стоимость.
При регистрации портфель пуст, стартового капитала нет. Это учебная симуляция:
программа не подключается к биржевым счетам и не совершает реальных сделок.
Баланс хранится как `float`, как в задании; вывод округляется отдельно от хранения.

## Курсы и Parser Service

`update-rates` получает BTC, ETH, SOL из CoinGecko и EUR, GBP, RUB из
ExchangeRate-API. Ключи читаются из переменных окружения; `.env.example` служит
образцом и автоматически не загружается. В PowerShell:

```powershell
$env:EXCHANGERATE_API_KEY = "ваш-ключ"
$env:COINGECKO_API_KEY = "ваш-demo-ключ"
uv run project
```

CoinGecko допускает запросы публичного endpoint без ключа; при ограничении
доступа можно задать Demo API key. Ключ передаётся в заголовке. Если ключ
ExchangeRate-API не задан, используется официальный Open Access endpoint.
Он обновляется раз в сутки; частые запросы не делают исходные данные новее.
Ограничения HTTP 401/403/429, таймауты, сетевые ошибки и некорректный JSON
выводятся понятным сообщением, без ключей и полного URL запроса.

Источники: [CoinGecko Simple Price](https://www.coingecko.com/learn/stream-real-time-crypto-prices-python),
[ExchangeRate-API Standard](https://www.exchangerate-api.com/docs/standard-requests),
[ExchangeRate-API Open Access](https://www.exchangerate-api.com/docs/free).
**Rates By [Exchange Rate API](https://www.exchangerate-api.com).**

Снимок `data/rates.json` содержит `pairs` и `last_refresh`. Все пары направлены
**из валюты в USD**: ответ фиатного API с базой USD инвертируется. Обратные и
кросс-курсы вычисляются через USD. Например, если API вернул USD→EUR = 0.8,
то EUR→USD = 1.25. Для BTC→EUR используется BTC→USD / EUR→USD.

TTL снимка — 300 секунд, настраивается в `[tool.valutatrade]` в `pyproject.toml`.
Время снимка означает время получения ответа, а не гарантированное время
изменения рыночной цены. Время обновления самого провайдера, если доступно,
сохраняется в `meta` истории. `get-rate`, сделки и оценка портфеля при просрочке
пытаются обновить данные. При неудаче устаревшая цена для сделки не используется.
`show-rates` работает без сети и явно помечает устаревшие строки.
У кросс-курса проверяется возраст обеих исходных пар, выводится более раннее время.

Парсер опрашивает источники независимо: сбой одного не мешает сохранить другой
и не удаляет предыдущие пары. Более старый ответ не заменяет новый. История
наблюдений хранится в `data/exchange_rates.json`; повтор одного id не добавляется.
Снимок истории не включён в репозиторий: реальные курсы загружаются локально.

Отдельный запуск парсера:

```console
uv run python -m valutatrade_hub.parser_service.scheduler --once
uv run python -m valutatrade_hub.parser_service.scheduler --interval 3600
```

Второй вариант работает до Ctrl+C, не устанавливает фоновую службу. Интервал
не меньше часа. Можно передать `--source coingecko` либо `--source exchangerate`.

## Структура

```text
main.py                         # точка входа project
valutatrade_hub/
  core/
    models.py                   # User, Wallet, Portfolio
    currencies.py               # Currency, FiatCurrency, CryptoCurrency, реестр
    exceptions.py               # доменные исключения
    usecases.py                 # регистрация, вход, сделки, портфель
    rates.py                    # TTL и конвертация
    utils.py                    # проверка чисел и UTC
  infra/
    settings.py                 # Singleton SettingsLoader
    database.py                 # Singleton DatabaseManager, JSON-транзакции
  parser_service/
    config.py                   # ParserConfig, env и параметры API
    api_clients.py              # BaseApiClient и два источника
    updater.py                  # RatesUpdater
    storage.py                  # снимок и история
    scheduler.py                # отдельный периодический запуск
  cli/interface.py              # разбор команд, сессия и вывод
  logging_config.py             # ротация JSON-журналов
  decorators.py                 # @log_action
data/                           # создаваемые при работе JSON-файлы
tests/                          # проверки с временными данными и HTTP-заглушками
docs/                           # запись демонстрации
Makefile
pyproject.toml
uv.lock
```

Пакет и `main.py` находятся в корне. Для сборки выбран `hatchling`, как в
уточнении преподавателя от 23 октября; wheel включает оба элемента.

## Данные и журналы

Данные создаются автоматически при первых операциях: `users.json`,
`portfolios.json`, `transactions.json`, `rates.json`, `exchange_rates.json`.
В репозитории нет пользовательских аккаунтов и API-ключей. Пароль хранится
как SHA-256 от пароля с уникальной случайной солью; в публичном методе
`get_user_info()` хеша и соли нет. Этот учебный формат соответствует заданию.

Запись JSON производится во временный файл с последующей заменой. Файловая
блокировка защищает read-modify-write от второго экземпляра приложения. Несколько
файлов сохраняются через журнал `.transaction.json`; после прерывания записи
следующее обращение завершает её. После ошибки диска сначала перечитайте
состояние, прежде чем повторять сделку. После аварийного завершения процесса
может остаться `.lock`: убедитесь, что других процессов приложения нет, сохраните
резервную копию данных и удалите только этот файл. Повреждённый JSON вызывает
ошибку; программа не заменяет его пустым файлом.

`logs/actions.log` содержит время UTC, действие, id, валюту, сумму, курс,
результат и ошибку; для успешных сделок также остатки до и после. Декоратор
`@log_action` повторно выбрасывает ошибки. `logs/parser.log` содержит этапы
обновления. JSON-журналы ротируются по 1 МиБ, сохраняются три резервные копии.
Исходные пароли, соли, хеши и ключи API не журналируются.

Пути можно изменить через `VALUTATRADE_DATA_DIR`, `VALUTATRADE_LOG_DIR`.
`VALUTATRADE_CONFIG` задаёт другой TOML с разделом `[tool.valutatrade]`.
Без конфигурационного файла используются значения по умолчанию; относительные
пути считаются от текущего рабочего каталога, включая запуск установленного wheel.

## Проверка и сборка

```console
uv run ruff check .
uv run python -m unittest discover -s tests -v
uv build
```

В Makefile доступны `install`, `project`, `lint`, `test`, `build`,
`package-install`, `publish`, `check`. `publish` предназначен для ручной
публикации пакета в реестре и при подготовке проекта не выполнялся.

## Демонстрация

Запись: [demo.cast](docs/demo.cast), просмотр: `asciinema play docs/demo.cast`.
Визуальная версия: [demo.gif](docs/demo.gif).
Демо использует явно обозначенные учебные HTTP-ответы, чтобы воспроизводиться
без сети и API-ключей. Обычный запуск приложения обращается к настоящим API.
Повторить сценарий: `uv run python docs/demo.py`.
