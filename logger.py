"""Логгер для FastAPI - простая адаптация."""

import contextvars
import enum
import json
import logging
import os
import typing as t
import uuid

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

# Опциональный импорт logstash
_with_logstash = True
try:
    import logstash
except ImportError:
    _with_logstash = False

# Для поддержки цветов на windows
if os.name == "nt":
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)


class ColorPicker(str, enum.Enum):
    debug = '\u001b[37m'  # light-gray
    info = '\u001b[34m'  # blue
    warn = '\u001b[33m'  # yellow
    error = '\u001b[31;1m'  # red, bold
    fatal = "\u001b[4;1;38;5;160m"  # RED, bold, underline
    end_of_hope = "\u001b[1;38;5;91m" + (
        b'(\xe2\x95\xaf\xc2\xb0\xe2\x96\xa1\xc2\xb0\xef\xbc\x89\xe2\x95\xaf'
        b'\xef\xb8\xb5 \xe2\x94\xbb\xe2\x94\x81\xe2\x94\xbb  '.decode()
    )
    clear = '\u001b[0m'

    @classmethod
    def pick(cls, level: int) -> str:
        if logging.DEBUG <= level < logging.INFO:
            return cls.debug
        if logging.INFO <= level < logging.WARNING:
            return cls.info
        if logging.WARNING <= level < logging.ERROR:
            return cls.warn
        if logging.ERROR <= level < logging.CRITICAL:
            return cls.error
        if logging.CRITICAL == level:
            return cls.fatal
        return cls.end_of_hope


class StdoutFormatter(logging.Formatter):
    """Форматтер с цветным выводом."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        declarer = record.__dict__.get("declarer", record.name)
        level_name = record.levelname
        res = f"[{declarer}] {level_name}: {message}"

        if data := record.__dict__.get("data", {}):
            if isinstance(data, dict):
                data["trace_id"] = FastAPILoggerAdapter.TRACE_ID.get()
                data["request_id"] = FastAPILoggerAdapter.REQUEST_ID.get()
            res += f" -> {data}"

        return f"{ColorPicker.pick(record.levelno)}{res}{ColorPicker.clear}"


if _with_logstash:
    class LogstashAdaptiveFormatter(logstash.LogstashFormatterVersion1):
        """Форматирование логов в Logstash."""

        DUMP_CLS = None

        @classmethod
        def serialize(cls, message):
            """Сериализация сообщения."""
            dumped = json.dumps(message, cls=cls.DUMP_CLS)
            return dumped.encode('utf-8')


class EndpointFilter(logging.Filter):
    """Фильтр эндпоинтов"""

    def __init__(self, path):
        self.path = path

    def filter(self, record):
        return record.args and len(record.args) >= 3 and record.args[
            2] != self.path


class FastAPILoggerAdapter(logging.LoggerAdapter):
    """Адаптер логгера для FastAPI."""

    APP_EXTRA = {}
    DEFAULT_TRACE_ID = 'root'
    DEFAULT_REQUEST_ID = 'no-request'
    TRACE_ID = contextvars.ContextVar('trace_id', default=DEFAULT_TRACE_ID)
    REQUEST_ID = contextvars.ContextVar(
        'request_id', default=DEFAULT_REQUEST_ID
    )

    @property
    def trace_id(self):
        return self.TRACE_ID.get(self.DEFAULT_TRACE_ID)

    @trace_id.setter
    def trace_id(self, value: str = None):
        self.TRACE_ID.set(value or self.DEFAULT_TRACE_ID)

    @property
    def request_id(self):
        return self.REQUEST_ID.get(self.DEFAULT_REQUEST_ID)

    @request_id.setter
    def request_id(self, value: str = None):
        self.REQUEST_ID.set(value or self.DEFAULT_REQUEST_ID)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.service_name = cls.__name__

    def __init__(self, **kwargs):
        super().__init__(logging.getLogger(), kwargs.pop('extra', {}))

    @classmethod
    def create(cls, issuer: t.Union[str, t.Type, object], **kwargs):
        """Основной способ инициализации."""
        logger = cls(**kwargs)
        logger.service_name = (
            issuer if isinstance(issuer, str) else type(issuer).__name__
        )
        return logger

    def process(self, msg, kwargs):
        """Обработка сообщения."""
        kwargs['extra'] = {
            'data': kwargs.get('extra') or {},
            'declarer': self.service_name,
            'trace_id': self.TRACE_ID.get(),
            'request_id': self.REQUEST_ID.get(),
            **self.extra,
            **self.APP_EXTRA,
        }
        return msg, kwargs


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware для автоматической установки request_id и trace_id."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        trace_id = request.headers.get('X-Trace-ID', str(uuid.uuid4()))

        FastAPILoggerAdapter.REQUEST_ID.set(request_id)
        FastAPILoggerAdapter.TRACE_ID.set(trace_id)

        response = await call_next(request)

        response.headers['X-Request-ID'] = request_id
        response.headers['X-Trace-ID'] = trace_id

        return response


def setup_logging(
        app: FastAPI,
        logstash_host: str = None,
        logstash_port: int = 5959,
        message_type: str = "fastapi",
        dump_cls: t.Type[json.JSONEncoder] | None = None,
        default_level: int = logging.INFO,
):
    """Настройка логирования для FastAPI."""

    # Очищаем существующие handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Создаем консольный handler с нашим форматтером
    console = logging.StreamHandler()
    console.setFormatter(StdoutFormatter())
    console.setLevel(default_level)

    # Настраиваем root logger
    root_logger.setLevel(default_level)
    root_logger.addHandler(console)

    # Настраиваем логгеры uvicorn для единообразия
    uvicorn_logger = logging.getLogger('uvicorn')
    uvicorn_access_logger = logging.getLogger('uvicorn.access')
    uvicorn_access_logger.addFilter(
        EndpointFilter('/api/v1/heartbeat/service-heartbeat/ping'))
    uvicorn_error_logger = logging.getLogger('uvicorn.error')
    uvicorn_error_logger.setLevel(logging.INFO)
    uvicorn_logger.handlers = [console]
    uvicorn_access_logger.handlers = [console]
    uvicorn_logger.propagate = False
    uvicorn_access_logger.propagate = False

    if logstash_host and _with_logstash:
        logstash_handler = logstash.TCPLogstashHandler(
            logstash_host,
            logstash_port,
            message_type=message_type,
            version=1,
        )
        logs_formatter = LogstashAdaptiveFormatter(
            message_type=message_type,
        )
        LogstashAdaptiveFormatter.DUMP_CLS = dump_cls
        logstash_handler.setFormatter(logs_formatter)
        logging.getLogger().addHandler(logstash_handler)
        FastAPILoggerAdapter.APP_EXTRA = {'app_name': message_type}

    # Добавляем middleware
    app.add_middleware(LoggingMiddleware)