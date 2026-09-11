"""Opaque backend-only credentials and fail-closed terminal entry."""

import getpass
import io
import os
import unicodedata
import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Never, SupportsIndex, TextIO

if os.name != "nt":
    import termios

KEY_NAME = "API_FOOTBALL_KEY"


class SecretValue:
    __slots__ = ("__value", "__usable")

    def __init__(self, value: str, *, usable: Callable[[], bool] | None = None):
        if (
            type(value) is not str
            or not value.strip()
            or len(value) > 512
            or any(unicodedata.category(c).startswith("C") for c in value)
        ):
            raise ValueError("E_SECRET_FORMAT")
        self.__value = value
        self.__usable = usable

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
        """Only the backend credential owner/transport may consume the value."""
        self.check_usable()
        return self.__value

    def check_usable(self) -> None:
        if self.__usable is not None and self.__usable() is not True:
            raise ValueError("E_SECRET_LEASE_LOST")


@contextmanager
def controlling_tty() -> Iterator[TextIO]:
    if os.name == "nt":
        raise ValueError("E_SECRET_NO_TTY")
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
