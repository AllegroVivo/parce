from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from parce.tree import Context, Token
    from parce.lexicon import Lexicon
    from parce.standardaction import StandardAction

type RootLexicon = Lexicon | Literal[False] | None
type Lexeme = tuple[int, str, StandardAction]
type ContextOrToken = Context | Token
type ChangeTuple = tuple[int, int, str]

type MaybeContext = Context | None
type MaybeToken = Token | None
type MaybeLexicon = Lexicon | None

type IntOrSlice = int | slice
