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


r"""
Query the tree using the `query` property of Context and Token.

Normally you need not to import this module in order to use it. Using the
:attr:`~.tree.Node.query` property of any Token or (in most cases) Context, you
can query the token tree to find tokens and contexts, based on lexicons and/or
actions and text contents. You can chain calls in an XPath-like fashion.

This module supplements the various find_xxx methods of every Context object. A
query is a generator, starts at the `query` property of a Context or Token
object, and initially yields just that object.

You can navigate using `children`, `all`, `first`, `last`, `[n]`, `[n:n]`,
`[n:n:n]`, `next`, `previous`, `right`, `left`, `right_siblings`,
`left_siblings`, `map()`, `parent` and `ancestors`. Use `uniq` to remove
double occurrences of nodes, which can e.g. happen when navigating to the
parent of all nodes.

You can narrow down the search using `tokens`, `contexts`, `remove_ancestors`,
`remove_descendants`, `slice()` and `filter()`.

You can search for tokens using `('text')` or `(lexicon)`, `startingwith()`,
`endingwith()`, `containing()`, `matching()`, `action()` or `in_action()`. The
special prefix `is_not` inverts the query, so `query.is_not.containing("bla")`
yields Tokens that do not contain the text "bla".


Examples:

Find all tokens that are the first child of a Context with bla lexicon::

    root.query.all(MyLang.bla)[0]


Find (in Xml) all attributes with name 'name' that are in a <bla> tag::

    root.query.all.action(Name.Tag)("bla").next('name')


Find all tags containing "hi" in their text nodes::

    root.query.all.action(Name.Tag).next.next.action(Text).containing('hi')


Find all comments that have TODO in it::

    root.query.all.action(Comment).containing('TODO')


Find all "\\version" tokens in the root context, that have a "2" in the version
string after it::

    (t for t in root.query.children('\\version')
        if t.query.next.next.containing('2'))

Which could also be written as::

    root.query.children('\\version').filter(
        lambda t: t.query.next.next.containing('2'))


A query is a generator, you can iterate over the results::

    for attrs in q.all.action(Name.Tag)('origin').right:
        for atr in attrs.query.action(Name.Attribute):
            print(atr)


For debugging purposes, there are also the ``list()`` construct, and the
``pick()``, ``count()`` and ``dump()`` methods::

    root.query.all.action(Name.Tag)("img").count() # number of "img" tags
    list(root.query.all.action(Name.Tag)("img"))   # list of all "img" tag name tokens


Note that a (partial) query can be reused, it simply restarts the iteration
over the results. The above could also be written as::

    q = root.query.all.action(Name.Tag)("img")
    q.count()   # number of "img" tags
    list(q)     # list of all "img" tag name tokens


A query resolves to False if there is no single result::

    if token.query.ancestors(LilyPond.header):
        do_something() # the token is a descendant of a LilyPond.header context


You can also directly instantiate a Query object for a list of nodes, if you
want to query those in one go::

    q = Query.from_nodes(nodes)



Summary of the query methods:
-----------------------------

Endpoint methods (some are mainly for debugging):

:attr:`~Query.ls`,
:meth:`~Query.count`,
:meth:`~Query.dump`,
:meth:`~Query.pick`,
:meth:`~Query.pick_last`,
:meth:`~Query.range` and
:meth:`~Query.delete`.


Navigating nodes:
^^^^^^^^^^^^^^^^^

The query itself just yields the node it was started from. But using the
following methods you can find your way through a tree structure. Every method
returns a new Query object, having the previous one as source of nodes. Most
methods are implemented as properties, so you don't have to write parentheses.

:attr:`~Query.all`,
:attr:`~Query.children`,
:attr:`~Query.parent`,
:attr:`~Query.ancestors`,
:attr:`~Query.next`,
:attr:`~Query.previous`,
:attr:`~Query.forward`,
:attr:`~Query.backward`,
:attr:`~Query.right`,
:attr:`~Query.left`,
:attr:`~Query.right_siblings`,
:attr:`~Query.left_siblings`,
:attr:`[n] <Query.__getitem__>`,
:attr:`[n:m] <Query.__getitem__>`,
:attr:`~Query.first`,
:attr:`~Query.last`, and
:meth:`~Query.map`,


Selecting (filtering) nodes:
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These methods filter out current nodes without adding new nodes
to the selection:

:attr:`~Query.tokens`,
:attr:`~Query.contexts`,
:attr:`~Query.uniq`,
:attr:`~Query.remove_ancestors`,
:attr:`~Query.remove_descendants`,
:meth:`~Query.slice` and
:meth:`~Query.filter`.

The special :attr:`~Query.is_not` operator inverts the meaning of the
next query, e.g.::

    n.query.all.is_not.startingwith("text")

The following query methods can be inverted by prepending `is_not`:

:meth:`~Query.len`,
:meth:`~Query.in_range`,
:meth:`(lexicon) <Query.__call__>`,
:meth:`(lexicon, lexicon2, ...) <Query.__call__>`,
:meth:`("text") <Query.__call__>`,
:meth:`("text", "text2", ...) <Query.__call__>`,
:meth:`~Query.startingwith`,
:meth:`~Query.endingwith`,
:meth:`~Query.containing`,
:meth:`~Query.matching`,
:meth:`~Query.action` and
:meth:`~Query.in_action`.

There is a subtle difference between `action` and `in_action`: with the
first, the action should exactly match, with the latter the tokens are
selected when the action exactly matches, or is a descendant of the given
action.

"""
from __future__ import annotations

from typing import (
    TYPE_CHECKING, Callable, Any, Iterator, Sequence, Optional, Tuple
)

import collections
import functools
import itertools
import re
import sys

if TYPE_CHECKING:
    from .tree import TokenOrContext, DumpStyle, Token, Context
    from _typeshed import SupportsWrite
    from .typeinfo import IntOrSlice
    from .standardaction import StandardAction

GeneratorFunc = Callable[[], Iterator["TokenOrContext"]]

def query(func: Callable) -> Callable[..., Query]:
    """Make a method result (generator) into a new Query object."""
    @functools.wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any):
        return Query(lambda: func(self, *args, **kwargs))
    return wrapper


def pquery(func: Callable) -> property:
    """Make a method result into a Query object, and the method a property."""
    return property(query(func))


class Query:
    """A Query navigates and filters a node tree.

    A Query is instantiated either by calling :attr:`Token.query
    <parce.tree.Node.query>` or :attr:`Context.query <parce.tree.Node.query>`,
    or by calling :meth:`Query.from_nodes` on a list of nodes (tokens and/or
    contexts).

    """
    __slots__ = '_gen', '_inv'

    def __init__(self, gen: GeneratorFunc, invert: bool = False):
        self._gen: GeneratorFunc = gen
        self._inv: bool = invert

    def __iter__(self) -> Iterator[TokenOrContext]:
        return self._gen()

    @classmethod
    def from_nodes(cls, nodes: Sequence[TokenOrContext]):
        """Create a Query object querying a list of nodes in one go."""
        return cls(lambda: iter(nodes))

    # end points
    def __bool__(self) -> bool:
        """Return True if there is at least one result."""
        for _ in self:
            return True
        return False

    # @property - Properties typically return something, converted to a function - SP
    def ls(self) -> None:
        """List current selection of this Query, for debugging purposes."""
        for i, n in enumerate(self):
            print("[{}] {}".format(i, repr(n)))

    def count(self) -> int:
        """Compute the length of the iterable."""
        return sum(1 for _ in self)

    def dump(
        self,
        file: Optional[SupportsWrite[str]] = None,
        style: Optional[DumpStyle] = None
    ) -> None:
        """Dump all selected nodes to the console (or to file).

        .. seealso:: :meth:`.tree.Node.dump`

        """
        for n in self:
            n.dump(file, style)

    def pick(self, default: Optional[TokenOrContext] = None) -> Optional[TokenOrContext]:
        """Pick the first value, or return the default."""
        for n in self:
            return n
        return default

    def pick_last(self, default: Optional[TokenOrContext] = None) -> Optional[TokenOrContext]:
        """Pick the last value, or return the default."""
        for default in self:
            pass
        return default

    def range(self) -> Tuple[int, int]:
        """Return the text range as a tuple (pos, end).

        The ``pos`` is the lowest pos of the nodes in the current set, and
        ``end`` is the highest end of the nodes.  If the result set is empty,
        (-1, -1) is returned.

        """
        pos = end = -1
        nodes = iter(self)
        for n in nodes:
            pos = n.pos
            end = n.end
            for n in nodes:
                pos = min(pos, n.pos)
                end = max(end, n.end)
        return pos, end

    def delete(self) -> int:
        """Delete all selected nodes from their parents.

        Internally calls ``uniq`` and ``remove_descendants``, so that no
        unnecessary deletes are done. If a context would become empty, that
        context itself is deleted instead of all its children (except for the
        root of course). Returns the number of nodes that were deleted.

        .. note::

           If you delete tokens from a tree which belong to a group, the tree
           cannot reliably be used by a treebuilder for a partial rebuild.

        """
        d = collections.defaultdict(list)
        for n in self.uniq.remove_descendants:
            d[n.parent].append(n)
        count = 0
        # deleting a root context makes no sense, clear it in that case
        roots = d.get(None)
        if roots:
            for root in roots:
                count += len(root)
                root.clear()
            del d[None]
        # if a parent looses all children, remove itself too
        while True:
            remove = [
                parent
                for parent, nodes in d.items()
                if len(nodes) == len(parent)
                and parent.parent is not None
            ]
            if not remove:
                break
            for n in remove:
                del d[n]
                d[n.parent].append(n)
        # be sure nodes to delete are sorted on pos
        for l in d.values():
            l.sort(key=lambda n: n.pos)
            count += len(l)
        for parent, nodes in d.items():
            n = nodes[0]
            i = 0 if n is parent[0] else n.parent_index()
            slices = [[i, i+1]]
            for n in nodes[1:]:
                if n is parent[i+1]:
                    i += 1
                    slices[-1][1] += 1
                else:
                    i = n.parent_index()
                    slices.append([i, i+1])
            for i, j in reversed(slices):
                del parent[i:j]
        return count

    # navigators
    @query
    def __getitem__(self, key: IntOrSlice) -> Iterator[TokenOrContext]:
        """Get the specified item or items of every context node.

        Note that the result nodes always form a flat iterable. No IndexError
        will be raised if an index would be out of range for any node.

        """
        # slicing or item-getting with integers are not invertible selectors
        from .tree import Context
        if isinstance(key, slice):
            for n in self:
                if isinstance(n, Context):
                    yield from n[key]
        else:
            for n in self:
                if isinstance(n, Context):
                    k = key + len(n) if key < 0 else key
                    if 0 <= k < len(n):
                        yield n[k]

    @pquery
    def children(self) -> Iterator[TokenOrContext]:
        """All direct children of the current nodes."""
        from .tree import Context
        for n in self:
            if isinstance(n, Context):
                yield from n

    @pquery
    def all(self):
        """All descendants, contexts and their nodes."""
        from .tree import Context
        def innergen(n):
            stack = []
            j = 0
            while True:
                assert n is not None
                for i in range(j, len(n)):
                    m = n[i]
                    yield m
                    if isinstance(m, Context):
                        stack.append(i)
                        j = 0
                        n = m
                        break
                else:
                    if stack:
                        n = n.parent
                        j = stack.pop() + 1
                    else:
                        break

        for n in self:
            yield n
            if isinstance(n, Context):
                yield from innergen(n)

    @pquery
    def alltokens(self) -> Iterator[Token]:
        """Shortcut for all.tokens."""
        from .tree import Token
        for n in self:
            if isinstance(n, Token):
                yield n
            else:
                yield from n.tokens()

    @pquery
    def allcontexts(self) -> Iterator[Context]:
        """Shortcut for all.contexts."""
        from .tree import Context
        def innergen(n):
            stack = []
            j = 0
            while True:
                assert n is not None  # for type checker - SP
                for i in range(j, len(n)):
                    m = n[i]
                    if isinstance(m, Context):
                        yield m
                        stack.append(i)
                        j = 0
                        n = m
                        break
                else:
                    if stack:
                        n = n.parent
                        j = stack.pop() + 1
                    else:
                        break
        for n in self:
            if isinstance(n, Context):
                yield n
                yield from innergen(n)

    @pquery
    def parent(self) -> Iterator[Context]:
        """Yield the parent of every node.

        This can lead to many double occurrences of the same node in the
        result set; use :attr:`~Query.uniq` to fix that.

        """
        for n in self:
            if n.parent:
                yield n.parent  # type: ignore - parent nodes are always a Context - SP

    @pquery
    def ancestors(self) -> Iterator[Context]:
        """Yield the ancestor contexts of every node."""
        for n in self:
            yield from n.ancestors()

    @pquery
    def first(self) -> Iterator[TokenOrContext]:
        """Yield the first node of every context node, same as [0]."""
        from .tree import Context
        for n in self:
            if n and isinstance(n, Context):
                yield n[0]

    @pquery
    def last(self) -> Iterator[TokenOrContext]:
        """Yield the last node of every context node, same as [-1]."""
        from .tree import Context
        for n in self:
            if n and isinstance(n, Context):
                yield n[-1]

    @pquery
    def next(self) -> Iterator[Token]:
        """Yield the next token, if any."""
        for n in self:
            t = n.next_token()
            if t:
                yield t

    @pquery
    def previous(self) -> Iterator[Token]:
        """Yield the previous token, if any."""
        for n in self:
            t = n.previous_token()
            if t:
                yield t

    @pquery
    def forward(self) -> Iterator[Token]:
        """Yield Tokens in forward direction."""
        for n in self:
            yield from n.forward()

    @pquery
    def backward(self) -> Iterator[Token]:
        """Yield Tokens in backward direction."""
        for n in self:
            yield from n.backward()

    @pquery
    def right(self) -> Iterator[TokenOrContext]:
        """Yield the right sibling, if any."""
        for n in self:
            n = n.right_sibling()
            if n:
                yield n

    @pquery
    def left(self) -> Iterator[TokenOrContext]:
        """Yield the left sibling, if any."""
        for n in self:
            n = n.left_sibling()
            if n:
                yield n

    @pquery
    def right_siblings(self) -> Iterator[TokenOrContext]:
        """Yield the right siblings, if any."""
        for n in self:
            yield from n.right_siblings()

    @pquery
    def left_siblings(self) -> Iterator[TokenOrContext]:
        """Yield the left siblings, if any."""
        for n in self:
            yield from n.left_siblings()

    @query
    def map(self, function: Callable[[TokenOrContext], Iterator[TokenOrContext]]) -> Iterator[TokenOrContext]:
        """Call the function on every node and yield its results, which should be zero or more nodes as well."""
        for n in self:
            yield from function(n)

    # selectors
    @query
    def filter(self, predicate: Callable[[TokenOrContext], bool]) -> Iterator[TokenOrContext]:
        """Yield nodes for which the predicate returns a value that evaluates to True."""
        for n in self:
            if predicate(n):
                yield n

    @pquery
    def tokens(self) -> Iterator[Token]:
        """Get only the tokens."""
        from .tree import Token
        for n in self:
            if isinstance(n, Token):
                yield n

    @pquery
    def contexts(self) -> Iterator[Context]:
        """Get only the contexts."""
        from .tree import Context
        for n in self:
            if isinstance(n, Context):
                yield n

    @pquery
    def uniq(self) -> Iterator[TokenOrContext]:
        """Remove double occurrences of the same node from the result set.

        This can happen e.g. when you find the parent of multiple nodes.

        """
        seen = set()
        for n in self:
            i = id(n)
            if i not in seen:
                seen.add(i)
                yield n

    @query
    def slice(self, *args: int) -> Iterator[TokenOrContext]:
        """Slice the full result set, using :py:func:`itertools.islice`.

        This can help narrowing down the result set. For example::

            root.query.all("blaat").slice(1).right_siblings.slice(3) ...

        will continue the query with only the first occurrence of a token
        "blaat", and then look for at most three right siblings. If the
        slice(1) were not there, all the right siblings would become one
        large result set because you wouldn't know how many tokens "blaat"
        were matched.

        """
        yield from itertools.islice(self, *args)

    @pquery
    def remove_descendants(self) -> Iterator[TokenOrContext]:
        """Remove nodes that have ancestors in the current node list."""
        ids = set(map(id, self))
        for n in self:
            if not any(id(p) in ids for p in n.ancestors()):
                yield n

    @pquery
    def remove_ancestors(self) -> Iterator[TokenOrContext]:
        """Remove nodes that have descendants in the current node list."""
        ids = set(map(id, self)) & set(map(id, (p for n in self for p in n.ancestors())))
        for n in self:
            if id(n) not in ids:
                yield n

    @property
    def is_not(self) -> Query:
        """Invert the next query."""
        return type(self)(self._gen, not self._inv)

    # invertible selectors
    @query
    def len(self, min_length: int, max_length: Optional[int] = None) -> Iterator[TokenOrContext]:
        """Only yield contexts, with min_length, or with length between min and max."""
        from .tree import Context
        if max_length is None:
            for n in self:
                if isinstance(n, Context) and self._inv ^ (len(n) == min_length):
                    yield n
        else:
            for n in self:
                if isinstance(n, Context) and self._inv ^ (min_length <= len(n) <= max_length):
                    yield n

    @query
    def in_range(self, start: int = 0, end: Optional[int] = None) -> Iterator[TokenOrContext]:
        """Yield a restricted set, tokens and/or contexts must fall in start→end"""
        if end is None:
            end = sys.maxsize
        # don't assume the tokens are in source order
        if self._inv:
            for n in self:
                if n.end <= start or n.pos >= end:
                    yield n
        else:
            for n in self:
                if n.pos >= start and n.end <= end:
                    yield n

    @query
    def __call__(self, *what: Sequence[TokenOrContext]) -> Iterator[TokenOrContext]:
        """Yield token if token has that text, or context if context has that lexicon.

        You can even mix the types if you'd need to::

            for n in tree.query.all("%", Lang.comment):
                # do something

        yields tokens that are a percent sign and contexts that have the
        Lang.comment lexicon.

        """
        from .tree import Token
        for n in self:
            if self._inv ^ ((n.text if isinstance(n, Token) else n.lexicon) in what):
                yield n

    @query
    def startingwith(self, text: str) -> Iterator[Token]:
        """Yield tokens that start with text."""
        from .tree import Token
        for t in self:
            if isinstance(t, Token) and self._inv ^ t.text.startswith(text):
                yield t

    @query
    def endingwith(self, text: str) -> Iterator[Token]:
        """Yield tokens that end with text."""
        from .tree import Token
        for t in self:
            if isinstance(t, Token) and self._inv ^ t.text.endswith(text):
                yield t

    @query
    def containing(self, text: str) -> Iterator[Token]:
        """Yield tokens that contain the specified text."""
        from .tree import Token
        for t in self:
            if isinstance(t, Token) and self._inv ^ (text in t.text):
                yield t

    @query
    def matching(self, pattern: re.Pattern[str], flags: re.RegexFlag = re.RegexFlag.NOFLAG) -> Iterator[Token]:
        """Yield tokens matching the regular expression.

        :func:`re.search` is used, so the expression can match anywhere
        unless you use ^ or $ characters).

        """
        from .tree import Token
        search = re.compile(pattern, flags).search
        for t in self:
            if isinstance(t, Token) and self._inv ^ bool(search(t.text)):
                yield t

    @query
    def action(self, *actions: StandardAction) -> Iterator[Token]:
        """Yield those tokens whose action *is* one of the given actions."""
        from .tree import Token
        for t in self:
            if isinstance(t, Token) and self._inv ^ (t.action in actions):
                yield t

    @query
    def in_action(self, *actions: StandardAction) -> Iterator[Token]:
        """Yield those tokens whose action *is or inherits from* one of the given actions."""
        from .tree import Token
        for t in self:
            if isinstance(t, Token) and self._inv ^ any(t.action in a for a in actions):
                yield t
