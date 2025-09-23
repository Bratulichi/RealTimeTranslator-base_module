"""Общие параметры компонентов."""
import abc
import json
import logging
import os
import typing as t

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlmodel import SQLModel, Field

T = t.TypeVar('T')


class BaseEnvFieldLoader(abc.ABC):
    """Базовый загрузчик поля из переменных окружения."""

    @abc.abstractmethod
    def __call__(self, value: str) -> t.Any:
        """Загрузить значение из переменных окружения."""


class EnvListLoader(BaseEnvFieldLoader):
    """Кастомный загрузчик для списковых значений."""

    def __init__(self, item_type: t.Type[T] = str,
                 item_separator: str = ','):
        self._item_type = item_type
        self._item_separator = item_separator

    def __call__(self, value: str) -> list[T]:
        if not value:
            return []
        return [
            self._item_type(v.strip())
            for v in value.split(self._item_separator)
            if v.strip()
        ]


KEY_TYPE = t.TypeVar('KEY_TYPE')
VALUE_TYPE = t.TypeVar('VALUE_TYPE')


class EnvDictLoader(BaseEnvFieldLoader):
    """Кастомный загрузчик словарных значений."""

    def __init__(
            self,
            key_type: t.Type[KEY_TYPE] = str,
            value_type: t.Type[VALUE_TYPE] = str,
            pair_separator: str = ',',
            key_value_separator: str = ':',
    ):
        self._key_type = key_type
        self._value_type = value_type
        self._pair_separator = pair_separator
        self._key_value_separator = key_value_separator

    def __call__(self, value: str) -> dict[KEY_TYPE, VALUE_TYPE]:
        if not value:
            return {}

        pairs = [
            entry.split(self._key_value_separator, 1)
            for entry in value.split(self._pair_separator)
            if entry.strip()
        ]
        return {
            self._key_type(k.strip()): self._value_type(v.strip())
            for k, v in pairs
        }


class BaseConfig(BaseSettings):
    """Базовый класс конфигурации с загрузкой из переменных окружения."""

    model_config = SettingsConfigDict(
        extra='ignore',
        case_sensitive=True,
    )

    _env_fields_loaders: t.ClassVar[dict[str, BaseEnvFieldLoader]] = {}

    @classmethod
    def parse_env_var(cls, field_name: str, raw_val: str) -> t.Any:
        """Парсинг кастомных значений из ENV'ов."""
        if field_name in cls._env_fields_loaders:
            return cls._env_fields_loaders[field_name](raw_val)
        return json.loads(raw_val)


class ModuleLoggingConfig(BaseConfig):
    """Параметры уровней логирования модулей Python."""

    name: str
    log_level: int


class SyslogProviderConfig(SQLModel):
    """Параметры для работы с внешней системой сбора логов."""

    host: str
    port: int
    message_type: str
    app_extra: dict = Field(default_factory=dict)


class EnvLoggerModulesLoader(BaseEnvFieldLoader):
    """Кастомный загрузчик для логгируемых модулей."""

    def __init__(self, separator: str = ',', entry_separator: str = ':'):
        self._separator = separator
        self._entry_separator = entry_separator

    def __call__(self, value: str) -> list[ModuleLoggingConfig]:
        modules = []
        if not value:
            return modules

        for entry in value.split(self._separator):
            if not entry.strip():
                continue
            name, log_level = entry.split(self._entry_separator, 1)
            modules.append(ModuleLoggingConfig(
                name=name.strip(),
                log_level=int(log_level.strip())
            ))
        return modules


class LoggerConfig(BaseConfig):
    """Параметры логирования."""

    model_config = SettingsConfigDict(
        extra='ignore',
        case_sensitive=True,
        env_nested_delimiter='__',
    )

    _env_fields_loaders: t.ClassVar[dict[str, BaseEnvFieldLoader]] = {
        'modules': EnvLoggerModulesLoader(),
    }

    root_log_level: int | str = Field(
        logging.INFO, alias='LOGGING_DEFAULT'
    )
    modules: list[ModuleLoggingConfig] = Field(
        default_factory=list,
        alias='LOGGING_MODULES'
    )
    logstash: SyslogProviderConfig | None = None


class BaseServiceConfig(BaseConfig):
    """Базовая конфигурация модуля с загрузкой из YAML."""

    CONFIG_PATH_KEY: t.ClassVar[str] = 'CONFIG_PATH'

    @classmethod
    def load(cls, config_data: dict[str, t.Any]) -> 'BaseServiceConfig':
        """Загрузить конфигурацию из словаря (обычно из YAML).

        Args:
            config_data: Словарь с данными конфигурации

        Returns:
            Экземпляр конфигурации
        """
        # Переносим конфигурацию модулей на верхний уровень для совместимости
        if 'modules' in config_data:
            modules_config = config_data.pop('modules')
            config_data['module'] = modules_config

        return cls(**config_data)

    @classmethod
    def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
    ):
        def yaml_settings_source() -> dict[str, t.Any]:
            config_path = os.getenv(cls.CONFIG_PATH_KEY, '/config.yaml')
            if not os.path.exists(config_path):
                return {}

            with open(config_path, 'r') as f:
                loaded = yaml.safe_load(f) or {}

            # Переносим конфигурацию модулей на верхний уровень
            modules_config = loaded.pop('modules', {})
            if modules_config:
                loaded['module'] = modules_config

            return loaded

        return (
            init_settings,
            yaml_settings_source,
            env_settings,
            file_secret_settings,
        )


class PgConfig(BaseConfig):
    """."""

    host: str = Field()
    port: int = Field()
    user: str = Field()
    password: str = Field()
    database: str = Field()
    max_pool_connections: int = Field(default=100)
    debug: bool = Field(default=False)
    db_schema: str = Field(default='public')


class ExternalPgConfig(PgConfig):
    """."""

    host: str = Field()
    port: int = Field()
    user: str = Field()
    password: str = Field()
    database: str = Field()
    db_schema: str = Field(default='external_modules')