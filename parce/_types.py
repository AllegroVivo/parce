"""
Shared type aliases for parce's annotations.

This module exists only for the type checker: everything in it is a PEP 695
``type`` alias, whose right-hand side is evaluated lazily.

The module is named ``_types`` and not ``types`` on purpose: a
``parce/types.py`` would shadow the stdlib :mod:`types` module whenever the
package directory ends up on ``sys.path``, and `parce.util` imports the
real one.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from parce.tree import Context, Token
    from parce.lexicon import Lexicon
    from parce.standardaction import StandardAction

# --- Tree Nodes ---
#: Any real node of a token tree, as ``Node`` is effectively abstract.
type ContextOrToken = Context | Token

# --- Lexing ---
#: The root lexicon slot of a tree or builder: a Lexicon, None for "no
#: lexicon", or False meaning "leave the current root lexicon unchanged".
type RootLexicon = Lexicon | Literal[False] | None

#: One match yielded by :func:`Lexicon.parse`: ``(pos, text, matchobj, action, target)``.
type LexiconParseTuple = tuple[int, str, re.Match[str] | None, Any, Target | None]

#: The signature of a compiled lexicon parse function.
type ParseFunc = Callable[[str, int], Iterator[LexiconParseTuple]]

#: One lexed token before tree building: ``(pos, text, action)``.
type Lexeme = tuple[int, str, StandardAction]

#: A lexicon rule: (pattern, action, *targets).
type LexiconRule = tuple[Any, ...]

# --- Documents ---
#: A single text change: ``(start, end, text)``
type ChangeTuple = tuple[int, int, str]


