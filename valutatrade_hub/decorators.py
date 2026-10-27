"""Декоратор аудита торговых операций."""

import inspect
import logging
from functools import wraps

from valutatrade_hub.logging_config import get_logger


def log_action(action=None, *, verbose=False):
    """Записать результат сценария и повторно выбросить его исключение."""

    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapper(*args, **kwargs):
            bound = signature.bind(*args, **kwargs).arguments
            event = {"action": action or function.__name__.upper(), "base": "USD"}
            # Белый список: пароль и другие переданные аргументы не попадут в лог.
            for key in ("user_id", "currency_code", "amount"):
                if key in bound:
                    value = bound[key]
                    event[key] = value if isinstance(value, (str, int)) else str(value)
            logger = get_logger("actions")
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                event.update(
                    result="ERROR",
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
                logger.log(logging.INFO, "", extra={"event": event})
                raise
            event.update(result="OK", rate=result.get("rate"))
            if verbose:
                event.update(before=result.get("before"), after=result.get("after"))
            logger.log(logging.INFO, "", extra={"event": event})
            return result

        return wrapper

    return decorate
