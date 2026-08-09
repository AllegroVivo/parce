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
A Target describes where to go.

In a lexicon rule, you can specify destinations using integers or lexicons.
A Target generalizes this in two values/attributes: ``pop`` and ``push``.

``pop`` is zero or a negative integer, determining how many lexicons to
pop off the current state/context.

``push`` is a tuple of zero or more lexicons, determining which lexicons to
add to the current state.

You can sort of "add" targets using a TargetFactory, which can create single
Target objects combining multiple targets in once.

"""
from __future__ import annotations

import itertools
from collections.abc import Iterable
from typing import Any, NamedTuple, TYPE_CHECKING

if TYPE_CHECKING:
    from parce.lexicon import Lexicon

class Target(NamedTuple):
    """Used by the :mod:`.lexer` to describe lexicon changes."""
    pop: int
    """A negative integer or 0, describing how many lexicons to leave."""
    push: tuple[Lexicon, ...]
    """A tuple of zero or more Lexicons to enter."""

class TargetFactory:
    """Maintains a current target and allows you to store changes.

    Call get() to get the final Target, and to reset the factory's internal
    state.

    """
    __slots__ = ('_pop', '_push')

    def __init__(self) -> None:
        self._pop: int = 0
        self._push: list[Lexicon] = []

    def add(self, target: Target | None) -> None:
        """Add a Target to this factory."""
        if target:
            if target.pop == 0:
                self._push.extend(target.push)
            elif -target.pop <= len(self._push):
                self._push[target.pop:] = target.push
            else:
                self._pop += len(self._push) + target.pop
                self._push[:] = target.push

    def get(self) -> Target | None:
        """Return the current :class:`Target`.

        Returns None if there is nothing to pop and push.
        After this the current target is reset.

        """
        if self._pop or self._push:
            t = Target(self._pop, tuple(self._push))
            self._pop = 0
            self._push.clear()
            return t
        return None

    def push(self, *lexicons: Lexicon) -> None:
        """Enter one or more lexicon(s)."""
        self._push.extend(lexicons)

    def pop(self, pop: int = -1) -> None:
        """Pop off one (or more) lexicon(s)."""
        if pop:
            if -pop <= len(self._push):
                del self._push[pop:]
            else:
                self._pop += len(self._push) + pop
                self._push.clear()

    @classmethod
    def make(cls, lexicon: Lexicon, rule: Iterable[Any]) -> Target | None:
        """Create a Target of a rule."""
        if rule:
            f = cls()
            for t in rule:
                if isinstance(t, int):
                    if t < 0:
                        f.pop(t)
                    elif t:
                        f.push(*itertools.repeat(lexicon, t))
                else:
                    f.push(t)
            return f.get()
        return None

