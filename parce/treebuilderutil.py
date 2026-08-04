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
Helper functions and classes for the :mod:`~parce.treebuilder` module.

"""
from __future__ import annotations

from collections.abc import Iterator, Sequence

from typing import Any, Literal, NamedTuple, TYPE_CHECKING, cast

import collections
import itertools

from . import util
from .lexer import Event, Lexer
from .tree import Context, Range, Token
from .target import TargetFactory

if TYPE_CHECKING:
    from parce.lexicon import Lexicon
    from parce.tree import Node
    from parce._types import RootLexicon


class BuildResult(NamedTuple):
    """Encapsulates the return values of :meth:`TreeBuilder.build_new_tree`."""
    tree: Context
    start: int
    end: int
    offset: int
    lexicons: list[Lexicon] | None


class ReplaceResult(NamedTuple):
    """Encapsulates the return values of :meth:`TreeBuilder.replace_tree`."""
    start: int
    end: int
    lexicons: list[Lexicon]  | None

class Changes:
    """Store changes that have to be made to a tree.

    This object is used by
    :meth:`~parce.treebuilder.TreeBuilder.get_changes()`. Calling
    :meth:`add()` merges new changes with the existing changes.

    """
    __slots__ = ("text", "root_lexicon", "start", "removed", "added")

    def __init__(self) -> None:
        self.text: str = ""
        self.root_lexicon: RootLexicon = False  # meaning no change is requested
        self.start: int = -1                    # meaning no text is altered
        self.removed: int = 0
        self.added: int = 0

    def __repr__(self) -> str:
        changes = []
        if self.root_lexicon != False:
            changes.append("root_lexicon: {}".format(self.root_lexicon))
        if self.start != -1:
            changes.append("text: {} -{} +{}".format(self.start, self.removed, self.added))
        if not changes:
            changes.append("(no changes)")
        return "<Changes {}>".format(', '.join(changes))

    def add(
        self,
        text: str,
        root_lexicon: RootLexicon = False,
        start: int =0,
        removed: int | None = None,
        added: int | None = None
    ) -> None:
        """Merge new change with existing changes.

        If added and removed are not given, all text after start is
        considered to be replaced.

        """
        if root_lexicon != False:
            self.root_lexicon = root_lexicon
        if removed is None:
            removed = len(self.text) - start
        if added is None:
            added = len(text) - start
        self.text = text
        if self.start == -1:
            # there were no previous changes
            self.start = start
            self.removed = removed
            self.added = added
            return
        # determine the offset for removed and added
        if start + removed < self.start:
            offset = self.start - start - removed
        elif start > self.start + self.added:
            offset = start - self.start - self.added
        else:
            offset = 0
        # determine which part of removed falls inside existing changes
        start = max(start, self.start)
        end = min(start + removed, self.start + self.added)
        offset -= max(0, end - start)
        # set the new values
        self.start = min(self.start, start)
        self.removed += removed + offset
        self.added += added + offset

    def has_changes(self) -> bool:
        """Return True when there are actually changes."""
        return self.start != -1 or self.root_lexicon != False

    def new_position(self, pos: int) -> int:
        """Return how the current changes would affect an older start."""
        if pos < self.start:
            return pos
        elif pos < self.start + self.removed:
            return self.start + self.added
        return pos - self.removed + self.added


def get_prepared_lexer(
    tree: Context,
    text: str,
    start: int,
    new_tree: bool = False
) -> tuple[Lexer, Iterator[Event], tuple[Token, ...]] | None:
    """Get a prepared lexer reading from text, positioned at (or before) start.

    Returns the three-tuple (lexer, events, tokens). The events stream is
    returned separately because the last Event can be pushed back, so it is
    yielded again. The tokens are the last tokens group that remained the same.

    Returns None when no position to start can be found, just start from the
    beginning in this case.

    If new_tree is True, does not find a start position if there would no
    tokens remain left of it. This is useful when restarting a tree build; it
    avoids leaving empty contexts in the build tree that should not be there.

    """
    last_token = find_token_before(tree, start)
    if not last_token:
        return None
    start_token = last_token
    go_back = backward(last_token)
    if last_token.group is not None and last_token.group >= 0:
        # we are in the middle of a group
        for last_token in go_back:
            if last_token.group is None or last_token.group < 0:
                break
        else:
            return None

    while start:
        # go back at least 10 tokens, to the beginning of a group; and don't
        # stop at the first token(group) of a context whose lexicon has
        # consume == True
        start = 0
        count = 10
        for start_token in go_back:
            for next_token in go_back:
                assert start_token.parent is not None
                if start_token.group is None and not (
                    start_token.is_first()
                    and start_token.parent.lexicon is not None
                    and start_token.parent.lexicon.consume
                ):
                    count -= 1
                    if count == 0:
                        start = start_token.pos
                        break
                start_token = next_token
            break
        if start:
            lexer = get_lexer(start_token)
        elif new_tree:
            return None
        else:
            assert tree.lexicon is not None
            lexer = Lexer([tree.lexicon])
        events = lexer.events(text, start)
        # compare the new events with the old tokens; at least one
        # should be the same; if not, go back further if possible
        old_events = events_with_tokens(start_token, last_token)
        prev = None
        for (old, tokens), new in zip(old_events, events):
            if not same_events(old, new):
                if prev:
                    return lexer, itertools.chain((new,), events), prev
                break
            prev = tokens
        else:
            if prev:
                return lexer, events, prev
    return None


def events_with_tokens(start_token: Token, last_token: Token) -> Iterator[tuple[Event, tuple[Token, ...]]]:
    r"""Yield (Event, tokens) tuples for start_token until and including last_token.

    Events are yielded together with token groups (or single tokens in a
    1-length tuple).

    This function is used by :func:`get_prepared_lexer` to compare an existing
    token structure with events originating from a lexer.

    The start_token must be the first of a group, if it is a GroupToken.
    Additionally, it should not be the first token in a context whose lexicon
    has the ``consume`` flag set. But if the start_token is the very first
    token in a tree, it does not matter if it is not in the root context, this
    case is handled gracefully.

    """
    context, start_trail, end_trail = common_ancestor_with_trail(start_token, last_token)
    if context:
        r = Range(context, start_trail, end_trail)

        target = TargetFactory()
        get, push, pop = target.get, target.push, target.pop

        def events(nodes: Sequence[Node]) -> Iterator[tuple[Event, tuple[Token, ...]]]:
            stack: list[int] = []
            i = 0
            n: Any = nodes  # a slice of a Context, or a Context itself
            while True:
                z = len(n)
                while i < z:
                    m = n[i]
                    if m.is_context:
                        push(m.lexicon)
                        stack.append(i)
                        i = 0
                        n = m
                        break
                    else:
                        group = m,
                        if m.group is not None:
                            # find the last token in this group
                            j = i + 1
                            while j < z and n[j].group > 0:
                                j += 1
                            group = n[i:j+1]
                        lexemes = tuple((t.pos, t.text, t.action) for t in group)
                        yield Event(get(), lexemes), group
                        i += len(group)
                else:
                    if stack:
                        pop()
                        i = stack.pop() + 1
                        n = n.parent if stack else nodes # slice we started with
                    else:
                        break

        assert start_token.parent is not None, "start_token must have a parent context"
        if start_token.is_first() and not start_token.parent.is_root() \
                and not any(backward(start_token)):
            # start token is the very first token, but it is not in the root
            # context. So it is a child of a lexicon with consume, or a context
            # that was jumped to via a default target. Build a target from root.
            lexicons = [p.lexicon for p in start_token.ancestors()]
            push(*lexicons[-2::-1])  # reversed, not root

        for context, slice_ in r.slices(target):
            yield from events(context[slice_])


def get_lexer(token: Token) -> Lexer:
    """Get a Lexer initialized at the token's ancestry."""
    lexicons = cast("list[Lexicon]", [p.lexicon for p in token.ancestors()])
    lexicons.reverse()
    return Lexer(lexicons)


def new_tree(token: Token) -> tuple[Context, Context]:
    """Return an empty context (and its root) with the same ancestry as the token's."""
    parent = token.parent
    assert parent is not None, "token must have a parent context"
    c = n = context = Context(parent.lexicon, None)
    for p in parent.ancestors():
        n = Context(p.lexicon, None)
        c.parent = n
        n.append(c)
        c = n
    return context, n


def find_token_before(node: Context, pos: int) -> Token | None:
    """A version of :meth:`Context.find_token_before()
    <parce.tree.Context.find_token_before>` that can handle empty contexts.

    The new tree built inside :meth:`TreeBuilder.build_new_tree()
    <parce.treebuilder.TreeBuilder.build_new_tree>` can have an empty context
    at the beginning and/or the end. Returns None if there is no token left
    from pos.

    """
    while True:
        i = 0
        hi = len(node)
        while i < hi:
            mid = (i + hi) // 2
            n = node[mid]
            if n.is_context:
                n = n.first_token() or n    # if no first token, just n itself
            if pos < n.end:
                hi = mid
            else:
                i = mid + 1
        if i == 0:
            return None
        node = node[i-1]
        if node.is_token:
            assert isinstance(node, Token), "node must be a Token if is_token is True"
            return node


def ancestors_with_index(node: Node) -> Iterator[tuple[Context, int]]:
    """A version of :meth:`Node.ancestors_with_index()
    <parce.tree.Node.ancestors_with_index>` that can handle empty contexts.

    """
    while node.parent:
        index = node.parent.index(node)
        node = node.parent
        yield node, index


def backward(node: Node) -> Iterator[Token]:
    """A version of :meth:`Node.backward() <parce.tree.Node.backward>` that can
    handle empty contexts.

    """
    for node, index in ancestors_with_index(node):
        if index:
            yield from util.tokens(node[:index], True)


def common_ancestor_with_trail(
    node: Node,
    other: Node
) -> tuple[Context | None, Sequence[int] | None, Sequence[int] | None]:
    """A version of :meth:`Token.common_ancestor_with_trail()
    <parce.tree.Token.common_ancestor_with_trail>` that can handle empty
    contexts.

    """
    if other is node:
        parent = node.parent
        assert parent is not None, "node must have a parent context"
        i = parent.index(node)
        return parent, (i,), (i,)
    if other.pos > node.pos:
        s_ancestors, s_indices = zip(*ancestors_with_index(node))
        o_indices = []
        for n, i in ancestors_with_index(other):
            o_indices.append(i)
            try:
                s_i = s_ancestors.index(n)
            except ValueError:
                continue
            return n, s_indices[s_i::-1], o_indices[::-1]
    return None, None, None


def same_events(e1: Event, e2: Event) -> bool:
    """Compare Event tuples in a robust way.

    Returns True if the events are completely the same. The lexicon in a target
    is compared on identity instead of equality. This prevents different
    derived lexicons from comparing the same, which is needed when rebuilding
    a tree.

    """
    if e1 != e2:
        return False
    elif e1.target is None or not e1.target.push:
        return True
    # both targets compare equal, and have a non-empty push value that compares
    # equal, so now we only need to compare the lexicons on identity.
    assert e2.target is not None, "e2.target must not be None if e1.target is not None"
    return all(l1 is l2 for l1, l2 in zip(e1.target.push, e2.target.push))


