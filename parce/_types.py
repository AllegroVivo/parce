from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Any

if TYPE_CHECKING:
    from parce.tree import Context, Token
    from parce.lexicon import Lexicon
    from parce.standardaction import StandardAction
    from parce.document import AbstractTextRange
    from parce.transform import Transformer

type RootLexicon = Lexicon | Literal[False] | None
type Lexeme = tuple[int, str, StandardAction]
type ContextOrToken = Context | Token
type ChangeTuple = tuple[int, int, str]
#: A lexicon rule: (pattern, action, *targets) - position determines meaning.
type LexiconRule = tuple[Any, ...]

type MaybeContext = Context | None
type MaybeToken = Token | None
type MaybeLexicon = Lexicon | None
type MaybeTransformer =  Transformer | None

type IntOrSlice = int | slice
type DocumentKey = IntOrSlice | AbstractTextRange
