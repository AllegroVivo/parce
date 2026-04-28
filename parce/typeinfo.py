from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from .standardaction import StandardAction


Lexeme = Tuple[int, str, StandardAction]
