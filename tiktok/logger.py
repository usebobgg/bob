from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TextIO

__all__ = [
    'ConsoleFormatter',
    'ContextFilter',
    'ContextLogger',
    'JsonFormatter',
    'LogConfig',
    'LogLevel',
    'LoggingSetupError',
    'bind',
    'configure_logging',
    'format_field_value',
    'get_logger',
    'normalise_key',
    'set_level',
]

ROOT_LOGGER_NAME = 'tiktok'
RESERVED_LOG_ARGUMENTS = frozenset({'exc_info', 'stack_info', 'stacklevel', 'extra'})
RESET_COLOUR = '\033[0m'
DIM_COLOUR = '\033[2m'

class LogLevel(Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

LEVEL_COLOURS: Mapping[int, str] = {
    logging.DEBUG: '\033[36m',
    logging.INFO: '\033[32m',
    logging.WARNING: '\033[33m',
    logging.ERROR: '\033[31m',
    logging.CRITICAL: '\033[1;31m',
}

@dataclass(frozen = True)
class LogConfig:
    level: LogLevel = LogLevel.INFO
    console_enabled: bool = True
    use_colour: bool | None = None
    show_context: bool = False
    message_width: int = 24
    file_path: Path | None = None
    file_level: LogLevel = LogLevel.DEBUG
    maximum_file_bytes: int = 5_000_000
    backup_count: int = 3

@dataclass
class LoggingState:
    console_handler: logging.Handler | None = None
    handlers: list[logging.Handler] = field(default_factory = list)

class LoggingSetupError(Exception):
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f'Could not open log file: {path}')

_context: ContextVar[Mapping[str, object]] = ContextVar('tiktok_log_context', default = {})
_state = LoggingState()

class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        call_fields: Mapping[str, object] = getattr(record, 'fields', {})
        record.fields = {normalise_key(key): value for key, value in call_fields.items()}
        record.context = {normalise_key(key): value for key, value in _context.get().items()}

        return True

class ContextLogger(logging.LoggerAdapter[logging.Logger]):
    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> tuple[Any, MutableMapping[str, Any]]:
        field_names = [name for name in kwargs if name not in RESERVED_LOG_ARGUMENTS]
        fields = {name: kwargs.pop(name) for name in field_names}
        kwargs['extra'] = {**(kwargs.get('extra') or {}), 'fields': fields}
        message = msg.lower() if isinstance(msg, str) else msg

        return message, kwargs

def normalise_key(key: str) -> str:
    return key.strip().lower().replace(' ', '_')

def format_field_value(value: object) -> str:
    if value is None or isinstance(value, bool):
        return str(value).lower()

    return str(value)

class ConsoleFormatter(logging.Formatter):
    def __init__(self, use_colour: bool, show_context: bool = False, message_width: int = 24) -> None:
        super().__init__()
        self._use_colour = use_colour
        self._show_context = show_context
        self._message_width = message_width

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
        level = f'{record.levelname:<8}'
        name = f'{record.name.removeprefix(f"{ROOT_LOGGER_NAME}."):<10}'
        call_fields: Mapping[str, object] = getattr(record, 'fields', {})
        context: Mapping[str, object] = getattr(record, 'context', {}) if self._show_context else {}
        fields = {**context, **call_fields}
        field_text = ' '.join(f'{key}={format_field_value(value)}' for key, value in fields.items())

        if self._use_colour:
            level = f'{LEVEL_COLOURS.get(record.levelno, "")}{level}{RESET_COLOUR}'
            timestamp = f'{DIM_COLOUR}{timestamp}{RESET_COLOUR}'
            name = f'{DIM_COLOUR}{name}{RESET_COLOUR}'
            field_text = f'{DIM_COLOUR}{field_text}{RESET_COLOUR}' if field_text else ''

        message = record.getMessage()
        line = f'{timestamp} {level} {name} {message}'

        if field_text:
            line = f'{timestamp} {level} {name} {message:<{self._message_width}}  {field_text}'

        if record.exc_info:
            line = f'{line}\n{self.formatException(record.exc_info)}'

        return line

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            'time': datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec = 'milliseconds'),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            **getattr(record, 'context', {}),
            **getattr(record, 'fields', {}),
        }

        if record.exc_info:
            entry['exception'] = self.formatException(record.exc_info)

        return json.dumps(entry, ensure_ascii = False, default = str)

def build_console_handler(config: LogConfig, stream: TextIO) -> logging.Handler:
    use_colour = stream.isatty() if config.use_colour is None else config.use_colour
    handler = logging.StreamHandler(stream)
    handler.setLevel(config.level.value)
    handler.setFormatter(ConsoleFormatter(use_colour, config.show_context, config.message_width))

    return handler

def build_file_handler(config: LogConfig, path: Path) -> logging.Handler:
    try:
        path.parent.mkdir(parents = True, exist_ok = True)
        handler = RotatingFileHandler(
            path,
            maxBytes = config.maximum_file_bytes,
            backupCount = config.backup_count,
            encoding = 'utf-8',
        )
    except OSError as E:
        raise LoggingSetupError(path) from E

    handler.setLevel(config.file_level.value)
    handler.setFormatter(JsonFormatter())

    return handler

def configure_logging(config: LogConfig = LogConfig(), stream: TextIO | None = None) -> None:
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)

    for handler in _state.handlers:
        root_logger.removeHandler(handler)
        handler.close()

    _state.handlers.clear()
    _state.console_handler = None

    if config.console_enabled:
        _state.console_handler = build_console_handler(config, stream or sys.stderr)
        _state.handlers.append(_state.console_handler)

    if config.file_path is not None:
        _state.handlers.append(build_file_handler(config, config.file_path))

    for handler in _state.handlers:
        handler.addFilter(ContextFilter())
        root_logger.addHandler(handler)

    root_logger.setLevel(min((handler.level for handler in _state.handlers), default = logging.WARNING))
    root_logger.propagate = False

def set_level(level: LogLevel) -> None:
    if _state.console_handler is None:
        return

    _state.console_handler.setLevel(level.value)
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    root_logger.setLevel(min(handler.level for handler in _state.handlers))

def get_logger(name: str) -> ContextLogger:
    is_namespaced = name == ROOT_LOGGER_NAME or name.startswith(f'{ROOT_LOGGER_NAME}.')
    full_name = name if is_namespaced else f'{ROOT_LOGGER_NAME}.{name}'

    return ContextLogger(logging.getLogger(full_name), {})

@contextmanager
def bind(**fields: object) -> Iterator[None]:
    token = _context.set({**_context.get(), **fields})

    try:
        yield
    finally:
        _context.reset(token)
