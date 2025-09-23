from __future__ import annotations

import typing as t
from enum import Enum

from pydantic import ConfigDict
from sqlmodel import SQLModel

from .exception import ModuleException


class ModelException(ModuleException):
    """."""

    prefix: str = 'ошибка обработки модели'


class ValuedEnum(str, Enum):
    """."""

    @classmethod
    def has_value(cls, value: t.Any) -> bool:
        return value in cls._value2member_map_

    @classmethod
    def values(cls) -> list[t.Any]:
        return list(cls._value2member_map_.keys())

    @classmethod
    def from_key(cls, key: str, safe: bool = True) -> ValuedEnum | None:
        member = cls.__members__.get(key)
        if member is None and not safe:
            raise ModelException(msg=f'Недопустимое значение: {key}',
                                 code=400)
        return member

    @classmethod
    def from_value(cls, value: t.Any,
                   safe: bool = True) -> ValuedEnum | None:
        for m in cls._value2member_map_.values():
            if m.value == value:
                return m
        if not safe:
            raise ModelException(msg=f'Недопустимое значение: {value}',
                                 code=400)
        return None

    @classmethod
    def from_name(cls, name: str):
        return cls._member_map_[name]

    @classmethod
    def to_dict(cls) -> dict[str, t.Any]:
        return {k: v.value for k, v in cls.__members__.items()}


TV_MODEL = t.TypeVar('TV_MODEL', bound='Model')


class Model(SQLModel, table=False):
    """."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_default=True,
        extra='forbid',
        from_attributes=True,
    )

    @classmethod
    def load(cls: type[TV_MODEL], data: t.Any) -> TV_MODEL:
        try:
            if isinstance(data, cls):
                return data
            return cls.model_validate(data)
        except Exception as e:
            raise ModelException(
                msg=f'Ошибка загрузки модели {cls.__name__}',
                details={'e': str(e), 'model': cls.__name__}
            ) from e

    def dump(self) -> dict[str, t.Any]:
        return self.model_dump()

    def update(self, data: dict[str, t.Any]) -> None:
        patched = self.model_copy(update=data)
        for k, v in patched.model_dump().items():
            object.__setattr__(self, k, v)

    def reload(self) -> TV_MODEL:
        return self.load(self.dump())

    def validate(self) -> None:
        self.model_validate(self.dump())


def view(cls: type[Model]):
    field_names = list(cls.model_fields)

    def _view(model: Model) -> dict[str, t.Any]:
        data = model.dump() if isinstance(model, Model) else dict(model)
        return {k: data[k] for k in field_names if k in data}

    return _view