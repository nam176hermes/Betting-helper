"""Ephemeral backend-only credentials. No storage, fingerprints or subprocess dispatch."""

import getpass
import io
import os
import termios
import unicodedata
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Never, SupportsIndex, TextIO

KEY_NAME = "API_FOOTBALL_KEY"


class SecretValue:
    __slots__ = ("__value",)

    def __init__(self, value: str):
        if (
            type(value) is not str
            or not value.strip()
            or len(value) > 512
            or any(unicodedata.category(c).startswith("C") for c in value)
        ):
            raise ValueError("E_SECRET_FORMAT")
        self.__value = value

    def __repr__(self) -> str:
        return "[REDACTED]"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return "[REDACTED]"

    def __hash__(self) -> int:
        raise TypeError("E_SECRET_SERIALIZATION")

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        raise TypeError("E_SECRET_SERIALIZATION")

    def __getstate__(self) -> object:
        raise TypeError("E_SECRET_SERIALIZATION")

    def reveal_for_header(self) -> str:
        """Only the fixed provider transport may consume this value outside tests."""
        return self.__value


@contextmanager
def controlling_tty() -> Iterator[TextIO]:
    try:
        terminal = io.TextIOWrapper(io.FileIO("/dev/tty", "r+"), encoding="utf-8")
        try:
            if not terminal.isatty():
                raise ValueError("E_SECRET_NO_TTY")
            termios.tcgetattr(terminal.fileno())
        except BaseException:
            terminal.close()
            raise
    except (OSError, ValueError, termios.error):
        raise ValueError("E_SECRET_NO_TTY") from None
    try:
        yield terminal
    finally:
        terminal.close()


def obtain_api_football_key(interactive: bool) -> SecretValue:
    if type(interactive) is not bool:
        raise ValueError("E_SECRET_MODE")
    with controlling_tty() as terminal:
        if not interactive:
            return SecretValue(os.environ.get(KEY_NAME, ""))
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass("API_FOOTBALL_KEY (hidden): ", stream=terminal)
        except (getpass.GetPassWarning, OSError, EOFError, termios.error):
            raise ValueError("E_SECRET_NO_ECHO") from None
        return SecretValue(value)
