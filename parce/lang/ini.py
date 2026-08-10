# -*- coding: utf-8 -*-
#
# This file is part of the parce Python package.
#
# Copyright © 2019-2020 by Wilbert Berendsen <info@wilbertberendsen.nl>
#
# This module is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
INI file format parsers.

The base parser supports escaped characters and line continuations for values.

"""
from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, cast

import re

from parce import Language, lexicon, default_action, default_target
from parce.action import (
    Bracket, Comment, Data, Delimiter, Escape, Name, Operator,
)
from parce.transform import Transform

if TYPE_CHECKING:
    from parce._types import LexiconRule
    from parce.standardaction import StandardAction
    from parce.transform import ItemList, Item


__all__ = ('Ini', 'IniTransform')


class Ini(Language):
    @lexicon
    def root(cls) -> Iterator[LexiconRule]:
        yield r'\[', Bracket.Start, cls.section
        yield r'[;#]', Comment, cls.comment
        yield r'=', Operator.Assignment, cls.value
        yield default_target, cls.key

    @lexicon
    def section(cls) -> Iterator[LexiconRule]:
        """Parse text between [ ... ]."""
        yield r'\]', Bracket.End, -1
        yield default_action, Name.Namespace

    @lexicon
    def key(cls) -> Iterator[LexiconRule]:
        """Yield a Name.Identifier until a '=' (if present)."""
        yield from cls.values(Name.Identifier)

    @lexicon
    def value(cls) -> Iterator[LexiconRule]:
        """Yield a Value until line end (or continuation line)."""
        yield from cls.values(Data)

    @classmethod
    def values(cls, action: StandardAction) -> Iterator[LexiconRule]:
        """Yield name or value contents and give it the specified action."""
        yield r"""\\(?:[\n\\'"0abtrn;#=:]|[xX][0-9a-fA-F]{4})""", Escape
        yield r"[^\[\\\n;=#:]+", action
        yield default_target, -1

    @lexicon(re_flags=re.MULTILINE)
    def comment(cls) -> Iterator[LexiconRule]:
        """Yield a Comment til the end of the line."""
        yield r'$', Comment, -1
        yield from cls.comment_common()


class IniTransform(Transform):
    """Transform for the Ini language definition.

    Strips whitespace around keys and values, and handles escaped characters.
    If a value is absent, None is stored.

    """
    def root(self, items: ItemList) -> dict[str, dict[str, str | None]]:
        """Return a dict, section names are the keys.

        Toplevel keys are in the ``None`` entry.

        """
        result: dict[str | None, dict[str, str | None]] = {}
        d = result[None] = {}
        i, z = 0, len(items)
        while i < z:
            if items.peek(i, "section"):
                result[cast("Item", items[i]).obj] = d = {}
            elif items.peek(i, "key", Operator.Assignment):
                key = cast("Item", items[i]).obj
                value = None
                if items.peek(i + 2, "value"):
                    value = cast("Item", items[i+2]).obj
                    i += 1
                d[key] = value
                i += 1
            i += 1
        # delete toplevel dict if empty
        if not result[None]:
            del result[None]
        return result  # type: ignore[return-value]

    def section(self, items: ItemList) -> str:
        """Return the name of the section."""
        if items.peek(-1, Bracket.End):
            items.pop()
        return self.values(items)

    def key(self, items: ItemList) -> str:
        """Return the key name."""
        return self.values(items)

    def value(self, items: ItemList) -> str | None:
        """Return the value."""
        return self.values(items)

    def values(self, items: ItemList) -> str:
        """Return a string, handling escaped characters, stripping spaces."""
        result = []
        if items:
            toks = list(items.tokens())
            # de-tokenize
            texts = [t.text for t in toks]
            # strip whitespace, but not from escapes
            if not texts[0].startswith('\\'):
                texts[0] = texts[0].lstrip(' \t')
            if not texts[-1].startswith('\\'):
                texts[-1] = texts[-1].rstrip(' \t')
            # unescape
            for t in texts:
                if t.startswith('\\'):
                    t = chr(int(t[2:], 16)) if t[1] in ('x', 'X') else t[1]
                result.append(t)
        return ''.join(result)

    comment = None


