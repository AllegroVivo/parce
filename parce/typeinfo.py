from __future__ import annotations

from typing import TYPE_CHECKING, Tuple, Optional

if TYPE_CHECKING:
    from .lexicon import Lexicon
    from .standardaction import StandardAction


Lexeme = Tuple[int, str, StandardAction]
RootLexicon = Optional[Lexicon]
