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

from typing import TYPE_CHECKING, List, Tuple, NamedTuple, Optional

import collections
import itertools

if TYPE_CHECKING:
    from .lexicon import Lexicon, RuleTuple

# Target = collections.namedtuple("Target", "pop push")
# Target.pop.__doc__ = "A negative integer or 0, describing how many lexicons to leave."
# Target.push.__doc__ = "A tuple of zero or more Lexicons to enter."

# Used by the :mod:`.lexer` to describe lexicon changes.
# Created in place of the above namedtuple, to add annotations to the fields. - SP
class Target(NamedTuple):
    """Target describes the movement between Lexicons during parsing."""
    pop: int
    """A negative integer or 0, describing how many lexicons to leave."""

    push: Tuple[Lexicon, ...]
    """A tuple of zero or more Lexicons to enter."""


class TargetFactory:
    """Maintains a current target and allows you to store changes.

    Call get() to get the final Target, and to reset the factory's internal
    state.

    """
    __slots__ = ('_pop', '_push')

    def __init__(self):
        self._pop: int = 0
        self._push: List[Lexicon] = []

    def add(self, target: Target):
        """Add a Target to this factory."""
        if target:
            if target.pop == 0:
                self._push.extend(target.push)
            elif -target.pop <= len(self._push):
                self._push[target.pop:] = target.push
            else:
                self._pop += len(self._push) + target.pop
                self._push[:] = target.push

    def get(self) -> Optional[Target]:
        """Return the current :class:`Target`.

        Returns None if there is nothing to pop and push.
        After this the current target is reset.

        """
        if self._pop or self._push:
            t = Target(self._pop, tuple(self._push))
            self._pop = 0
            self._push.clear()
            return t

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
    def make(cls, lexicon: Lexicon, rule) -> Optional[Target]:  # TODO: type rule - DP
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
