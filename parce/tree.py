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
This module defines the tree structure a text is parsed into.

A tree consists of Context and Token objects. (Both inherit from the base
class Node, which defines the shared methods and properties.)

A :class:`Context` is a list containing Tokens and other Contexts. A Context is
created when a lexicon becomes active. A Context knows its parent Context and
its lexicon.

A :class:`Token` represents one parsed piece of text. A Token is created when a
rule in the lexicon matches. A Token knows its parent Context, its position in
the text and the action that was specified in the rule.

A Context is always non-empty, except for the root Context, which represents
the root lexicon and can be empty if the document did not generate a single
token.

The tree structure is easy to navigate, no special objects or iterators are
necessary for that. To find a token at a certain position in a context, use
:meth:`Context.find_token` and its relatives. From every node you can iterate
:meth:`~Node.forward` and :meth:`~Node.backward`. Use the methods like
:meth:`~Node.left_siblings` and :meth:`~Node.right_siblings` to traverse the
current context.

"""
from __future__ import annotations

import reprlib
import weakref
from collections.abc import Iterator
from typing import TYPE_CHECKING, Optional, Callable, Literal, Iterable, List, Tuple, Self, Union, Sequence, overload

from parce import util
from parce.lexicon import Lexicon
from parce.query import Query

if TYPE_CHECKING:
    from _typeshed import SupportsWrite
    from .standardaction import StandardAction
    from .typeinfo import Lexeme
    from .target import TargetFactory

DUMP_STYLES = {
    "ascii":   (" | ", "   ", " |-", " `-"),
    "round":   (" │ ", "   ", " ├╴", " ╰╴"),
    "square":  (" │ ", "   ", " ├╴", " └╴"),
    "double":  (" ║ ", "   ", " ╠═", " ╚═"),
    "thick":   (" ┃ ", "   ", " ┣╸", " ┗╸"),
    "flat":    ( "│",   " ",   "├",   "╰" ),
}

DumpStyle = Literal["ascii", "round", "square", "double", "thick", "flat"]
DUMP_STYLE_DEFAULT: DumpStyle = "round"

TokenOrContext = Union["Token", "Context"]
IndexTrail = List[int]

class Node:
    """Methods that are shared by Token and Context.

    Note: This class intentionally avoids using __slots__ to remain
    compatible with the C-level memory layout of the 'list' class,
    from which Context inherits. This ensures that all Node instances
    support dynamic attributes and weak references by default. - SP
    """
    # __slots__ = ('__weakref__', "_parent")

    # Initialized here to provide a consistent interface for all tree methods.
    _parent: Callable[[], Optional[Context]] = None
    pos: int = 0

    is_token: bool = False
    is_context: bool = False

    # noinspection PyUnreachableCode
    def __iter__(self) -> Iterable[TokenOrContext]:
        """For typing compatibility - SP"""
        return
        yield

    def __len__(self) -> int:
        """For typing compatibility - SP"""
        return 0

    @property
    def parent(self) -> Optional[Context]:
        """The parent Context (or None; uses a weak reference)."""
        return self._parent()

    @parent.setter
    def parent(self, parent: Optional[Context]) -> None:
        """Set the parent (to a Context or None)."""
        self._parent = weakref.ref(parent) if parent is not None else lambda: None

    @parent.deleter
    def parent(self) -> None:
        """Set the parent to None."""
        self._parent = lambda: None

    def copy(self, parent: Optional[Context] = None) -> Self:
        """Return a copy of the Node, but with the specified parent."""
        raise NotImplementedError

    def dump(
        self,
        file: Optional[SupportsWrite[str]] = None,
        style: Optional[DumpStyle] = None,
        depth: int = 0
    ) -> None:
        """Display a graphical representation of the node and its contents.

        The file object defaults to stdout, and the style to "round". You can
        choose any style that's in the ``DUMP_STYLES`` dictionary.

        """
        i = 2
        d = DUMP_STYLES[style or DUMP_STYLE_DEFAULT]
        prefix = []
        node: Node = self
        for _ in range(depth):
            prefix.append(d[i + int(node.is_last())])
            node = node.parent  # type: ignore - Context is fine here
            i = 0
        print("".join(reversed(prefix)) + repr(self), file=file)
        if self.is_context:
            for n in self:
                n.dump(file, style, depth + 1)

    # @property - Properties typically return something, converted to a function - SP
    def pwd(self):
        """Show the ancestry, for debugging purposes."""
        nodes: List[Node] = [self]
        nodes.extend(self.ancestors())
        nodes.reverse()
        d = DUMP_STYLES[DUMP_STYLE_DEFAULT]
        for n, node in enumerate(nodes):
            # Reworked to appease the typechecker - SP
            parent = nodes[n - 1] if n > 0 else None
            index_str = ""
            if n > 0 and isinstance(parent, list):
                index_str = " [{}]".format(parent.index(node))
            print(''.join((
                d[1] * max(0, n-1),
                d[3] if n else '',
                repr(node),
                index_str,
            )))

    def parent_index(self) -> int:
        """Return our index in the parent.

        This is recommended above using parent.index(self), because this method
        finds our index using a binary search on position, while the latter
        is a linear search, which is certainly slower with a large number of
        children.

        """
        p = self.parent
        assert p  # Ensure parent is not None for typechecker - SP
        pos = self.pos
        lo = 0
        hi = len(p)
        while lo < hi:
            mid = (lo + hi) // 2
            n = p[mid]
            if n.pos < pos:
                lo = mid + 1
            elif n is self:
                return mid
            else:
                hi = mid
        return lo

    def root(self) -> Context:
        """Return the root node."""
        root = self
        for root in self.ancestors():
            pass
        return root  # type: ignore - Only Contexts can be roots

    def is_last(self) -> bool:
        """Return True if this Node is the last child of its parent.

        Fails if called on the root element.

        """
        p = self.parent  # Updated to appease typechecker - SP
        if p is not None:
            return p[-1] is self
        raise ValueError("is_last() called on root element")

    def is_first(self):
        """Return True if this Node is the first child of its parent.

        Fails if called on the root element.

        """
        p = self.parent  # Updated to appease typechecker - SP
        if p is not None:
            return p[0] is self
        raise ValueError("is_first() called on root element")

    def is_ancestor_of(self, node: Node) -> bool:
        """Return True if this Node is an ancestor of the other Node."""
        for n in node.ancestors():
            if n is self:
                return True
        return False

    def ancestors(self, upto: Optional[Node] = None) -> Iterator[Context]:
        """Climb the tree up over the parents.

        If upto is given, and it is one of the ancestors, stop after yielding
        that ancestor. Otherwise, iteration stops at the root node.

        """
        node = self.parent
        if upto and upto.parent is not None:
            p = upto.parent
            while node is not None and node is not p:
                assert node is not None
                yield node
                node = node.parent
        else:
            while node is not None:
                assert node is not None
                yield node
                node = node.parent

    def ancestors_with_index(
        self,
        upto: Optional[Node] = None
    ) -> Iterable[Tuple[Context, int]]:
        """Yield the ancestors(upto), and the index of each node in the parent."""
        n: Node = self
        for p in self.ancestors(upto):
            yield p, n.parent_index()
            n = p

    def common_ancestor(self, other: Node) -> Optional[TokenOrContext]:
        """Return the common ancestor with the Context or Token."""
        ancestors = []
        if self.is_context:
            ancestors.append(self)
        ancestors.extend(self.ancestors())
        if other.is_context and other in ancestors:
            return other  # type: ignore - is context by this point
        for n in other.ancestors():
            if n in ancestors:
                return n

    def depth(self) -> int:
        """Return the number of ancestors."""
        return sum(1 for _ in self.ancestors())

    def left_sibling(self):
        """Return the left sibling of this node, if any.

        Does not descend in child nodes or ascend upto the parent.
        Fails if called on the root node.

        """
        p = self.parent  # Updated to appease typechecker - SP
        if p is not None and p[0] is not self:
            i = self.parent_index()
            return p[i-1]
        raise ValueError("left_sibling() called on root element or first child")

    def right_sibling(self):
        """Return the right sibling of this node, if any.

        Does not descend in child nodes or ascend upto the parent.
        Fails if called on the root node.

        """
        p = self.parent  # Updated to appease typechecker - SP
        if p is not None and p[-1] is not self:
            i = self.parent_index()
            return p[i+1]
        raise ValueError("right_sibling() called on root element or last child")

    def left_siblings(self) -> Iterable[TokenOrContext]:
        """Yield the left siblings of this node in reverse order, if any.

        Does not descend in child nodes or ascend upto the parent.
        Fails if called on the root node.

        """
        p = self.parent
        if p is not None and p[0] is not self:
            i = self.parent_index()
            yield from p[i-1::-1]
        else:
            raise ValueError("left_siblings() called on root element or first child")

    def right_siblings(self) -> Iterable[TokenOrContext]:
        """Yield the right siblings of this node, if any.

        Does not descend in child nodes or ascend upto the parent.
        Fails if called on the root node.

        """
        p = self.parent
        if p is not None and p[-1] is not self:
            i = self.parent_index()
            yield from p[i+1:]
        else:
            raise ValueError("right_siblings() called on root element or last child")

    def next_token(self) -> Optional[Token]:
        """Return the following Token, if any."""
        for t in self.forward():
            return t

    def previous_token(self) -> Optional[Token]:
        """Return the preceding Token, if any."""
        for t in self.backward():
            return t

    def forward(self, upto: Optional[Node] = None) -> Iterable[Token]:
        """Yield all Tokens in forward direction, starting at the right sibling.

        Descends into child Contexts, and ascends into parent Contexts.
        If upto is given, does not ascend above that context.

        """
        for parent, index in self.ancestors_with_index(upto):
            yield from util.tokens(parent[index+1:])

    def backward(self, upto: Optional[Node] = None) -> Iterable[Token]:
        """Yield all Tokens in backward direction, starting at the left sibling.

        Descends into child Contexts, and ascends into parent Contexts.
        If upto is given, does not ascend above that context.

        """
        for parent, index in self.ancestors_with_index(upto):
            if index:
                yield from util.tokens(parent[:index], True)

    @property
    def query(self) -> Query:
        """Query this node in different ways; see the :mod:`~parce.query` module."""
        def gen() -> Iterator[TokenOrContext]:
            yield self  # type: ignore
        return Query(gen)

    def delete(self) -> Optional[Context]:
        """Remove this node from its parent.

        If the parent becomes empty, it is removed too.
        Returns the first non-empty ancestor.

        """
        for parent, index in self.ancestors_with_index():
            del parent[index]
            if len(parent):
                return parent


class Token(Node):
    """A Token instance represents a lexed piece of text.

    When a pattern rule in a lexicon matches the text, a Token is created. When
    that rule would create more than one Token from a single regular expression
    match, GroupToken objects are created instead, carrying the index of the
    token in the group in the `group` attribute. The `group` attribute is
    readonly None for normal tokens.

    GroupTokens are thus always adjacent in the same context. If you want to
    retokenize text starting at some position, be sure you are at the start of
    a grouped token, e.g.::

        t = ctx.find_token(45)
        if t.group:
            for t in t.left_siblings():
                if not t.group:
                    break
        pos = t.pos

    Alternatively, you can use the `GroupToken.get_group_*` methods.

    (A GroupToken is just a normal Token otherwise, the reason a subclass was
    created is that the group attribute is unused in by far the most tokens, so
    it does not use any memory. You never need to reference the GroupToken
    class; just test the group attribute if you want to know if a token belongs
    to a group that originated from a single match.)

    When iterating over the children of a Context (which may be Context or
    Token instances), you can use the `is_token` attribute to determine whether
    the node child is a token, which is easier than to call `isinstance(t,
    Token)` each time.

    From a token, you can iterate `forward()` or `backward()` to find adjacent
    tokens. If you only want to stay in the current context, use the various
    sibling methods, such as `right_sibling()`.

    By traversing the `ancestors()` of a token or context, you can find which
    lexicons created the tokens.

    You can compare a Token instance with a string. Instead of::

        if token.text == "bla":
            do_something()

    you can do::

        if token == "bla":
            do_something()

    You can call `len()` on a token, which returns the length of the token's
    text attribute, and you can use the string format method to embed the
    token's text in another string::

        s = "blabla {}".format(token)

    A token always has a parent, and that parent is always a Context instance.

    """

    __slots__ = ("pos", "text", "action")

    group: int = None       #: Always None for Token, an integer for :class:`GroupToken`
    is_token: bool = True   #: Always True for Token

    def __init__(self, parent: Optional[Context], pos: int, text: str, action: StandardAction):
        self.parent: Optional[Context] = parent  #: The Context node to which the token was added
        self.pos: int = pos                      #: The position in the original text
        self.text: str = text                    #: The text of this token
        self.action: StandardAction = action     #: The action specified by the lexicon rule that created the token

    @property
    def end(self) -> int:
        """The end position of this token in the original text."""
        return self.pos + len(self.text)

    def copy(self, parent: Optional[Context] = None) -> Self:
        """Return a copy of the Token, but with the specified parent."""
        return type(self)(parent, self.pos, self.text, self.action)  # type: ignore - this is fine - SP

    def equals(self, other: Token) -> bool:
        """Return True if the other Token has the same ``text`` and ``action``
        attributes and the same context ancestry (see also
        :meth:`state_matches`).

        Note that the ``pos`` attribute is not compared.

        """
        return (
            self.text == other.text
            and self.action == other.action
            and self.state_matches(other)
        )

    def state_matches(self, other: Token) -> bool:
        """Return True if the other Token has the same lexicons in the ancestors."""
        # Updated to appease typechecker - SP
        if other is self:
            return True
        c1 = c2 = None
        for c1, c2 in zip(self.ancestors(), other.ancestors()):
            if c1 is not None and c1 is c2:
                return True
            elif c1 is not None and c2 is not None and c1.lexicon is not c2.lexicon:
                return False
        return (
            c1 is not None and c2 is not None
            and isinstance(c1, Token) and isinstance(c2, Token)
            and c1.parent is None and c2.parent is None
        )

    def __repr__(self) -> str:
        text = reprlib.repr(self.text)
        return "<Token {} at {}:{} ({})>".format(text, self.pos, self.end, self.action)

    def __hash__(self) -> int:
        return Node.__hash__(self)

    def __eq__(self, other: Union[Token, str]) -> bool:
        if isinstance(other, str):
            return other == self.text
        return other is self

    def __ne__(self, other: Union[Token, str]) -> bool:
        if isinstance(other, str):
            return other != self.text
        return other is not self

    def __format__(self, formatstr: str) -> str:
        return self.text.__format__(formatstr)

    def __len__(self) -> int:
        return len(self.text)

    def forward_including(self, upto: Optional[Token] = None) -> Iterable[Token]:
        """Yield all tokens in forward direction, including self."""
        yield self
        yield from self.forward(upto)

    def backward_including(self, upto: Optional[Token] = None) -> Iterable[Token]:
        """Yield all tokens in backward direction, including self."""
        yield self
        yield from self.backward(upto)

    def forward_until_including(self, other: Token) -> Iterable[Token]:
        """Yield all tokens starting with us and upto and including the other."""
        r = self.range(other)
        if r:
            yield from r.tokens()

    def common_ancestor_with_trail(
        self,
        other: Token
    ) -> Tuple[Optional[Context], Optional[List[int]], Optional[List[int]]]:
        """Return a three-tuple(context, trail_self, trail_other).

        The context is the common ancestor such as returned by common_ancestor,
        if any. trail_self is a tuple of indices from the common ancestor upto
        self, and trail_other is a tuple of indices from the same ancestor upto
        the other Token.

        If there is no common ancestor, all three are None. But normally,
        all nodes share the root context, so that will normally be the upmost
        common ancestor.

        """
        if other is self:
            i = self.parent_index()
            return self.parent, [i], [i]  # Changed to list so returns are uniform - SP
        if other.pos > self.pos:
            s_ancestors, s_indices = zip(*self.ancestors_with_index())
            s_indices: IndexTrail  # for typechecker - SP
            o_indices: IndexTrail = []
            for n, i in other.ancestors_with_index():
                o_indices.append(i)
                try:
                    s_i = s_ancestors.index(n)
                except ValueError:
                    continue
                return n, s_indices[s_i::-1], o_indices[::-1]
        return None, None, None

    def range(self, other: Token) -> Optional[Range]:
        """Return a :class:`Range` from this token upto and including the other.

        Returns None if the other :class:`Token` does not belong to the same
        tree.

        """
        context, start_trail, end_trail = self.common_ancestor_with_trail(other)
        if context:
            return Range(context, start_trail, end_trail)


class GroupToken(Token):
    """A Token class that allows setting the `group` attribute.

    For normal Token instances, `group` is a class attribute that is always
    None. For Tokens that belong to a group, i.e. originated from a single
    regular expression match, the `group` attribute is the index of the token
    in the group of tokens that were created together.

    The last token in the group has a negative value, so it can be recognized
    as the last. For example, tokens of a three-group have the indices 0, 1 and
    -2.

    The methods :meth:`get_group`, :meth:`get_group_start` and
    :meth:`get_group_end` can only be reliably used when there are no tokens
    deleted from the tree, and when the tokens really have a parent.

    """
    __slots__ = ("group",)

    def __init__(
        self,
        group: int,
        parent: Optional[Context],
        pos: int,
        text: str,
        action: StandardAction
    ):
        self.group: int = group  #: The index of this token in a group (negative value for the last token in a group)
        super().__init__(parent, pos, text, action)

    def copy(self, parent: Context = None) -> GroupToken:
        """Return a copy of the Token, but with the specified parent."""
        assert parent is not None
        return type(self)(self.group, parent, self.pos, self.text, self.action)

    @classmethod
    def make_group(cls, parent: Optional[Context], lexemes: Sequence[Lexeme]) -> Tuple[GroupToken, ...]:
        """Create a tuple of GroupTokens for the lexemes."""
        group = tuple(cls(n, parent, *t) for n, t in enumerate(lexemes))
        group[-1].group *= -1
        return group

    def get_group(self) -> Union[TokenOrContext, List[TokenOrContext]]:
        """Return the whole group this token belongs to as a list."""
        p = self.parent
        assert p  # Ensure parent is not None for typechecker - SP
        i = j = self.parent_index()
        z = len(p) - 1
        if self.group < 0:
            # we are at the last
            i += self.group
        else:
            i -= self.group
            j += 1
            while j < z:  # updated to appease typechecker - SP
                sibling = p[j]
                if isinstance(sibling, Token) and sibling.group > 0:
                    j += 1
                else:
                    break
        return p[i:j+1]

    def get_group_start(self):
        """Return the first token of the group this token belongs to."""
        i = self.parent_index()
        if self.group < 0:
            i += self.group
        else:
            i -= self.group
        parent = self.parent
        assert parent  # Ensure parent is not None for typechecker - SP
        return parent[i]

    def get_group_end(self):
        """Return the last token of the group this token belongs to."""
        p = self.parent
        assert p  # Ensure parent is not None for typechecker - SP
        i = self.parent_index()
        z = len(p) - 1
        if self.group >= 0:
            i += 1
            while i < z:  # updated to appease typechecker - SP
                sibling = p[i]
                if isinstance(sibling, Token) and sibling.group > 0:
                    i += 1
        return p[i]


class Context(list[TokenOrContext], Node):
    """A Context represents a list of tokens and contexts.

    The lexicon that created the tokens is in the `lexicon` attribute.

    If a pattern rule jumps to another lexicon, a sub-Context is created and
    tokens are added there. If that lexicon pops back to the current one, new
    tokens can appear after the sub-context. (So the token that caused the jump
    to the sub-context normally precedes the context it created.)

    A context has a `parent` attribute, which can point to an enclosing
    context. The root context has `parent` None.

    When iterating over the children of a Context (which may be Context or
    Token instances), you can use the `is_context` attribute to determine
    whether the node child is a context, which is easier than to call
    `isinstance(node, Context)` each time.

    You can quickly find tokens in a context, based on text::

        if "bla" in context:
            # etc

    Or child contexts, based on lexicon::

        if MyLanguage.lexicon in context:
            # etc

    And if you want to know which token is on a certain position in the text,
    use e.g.::

        context.find_token(45)

    which, using a bisection algorithm, quickly returns the token, which
    might be in any sub-context of the current context.

    """
    __slots__ = ("lexicon",)

    is_context: bool = True   #: Always True for Context

    def __new__(cls, lexicon, parent):
        return list.__new__(cls)  # type: ignore - this is fine, we inherit from list - SP

    def __init__(self, lexicon: Lexicon, parent: Optional[Context]):
        super().__init__()
        self.lexicon: Lexicon = lexicon  #: The lexicon this context was instantiated with.
        self.parent: Optional[Context] = parent

    def __repr__(self) -> str:
        pos, end = self.pos, self.end
        if pos == end:
            pos = end = "?"  # both are 0 in this case: empty Context
        name = self.lexicon and repr(self.lexicon)
        children = "child" if len(self) == 1 else "children"
        return "<Context {} at {}-{} ({} {})>".format(
            name, pos, end, len(self), children
        )

    def __hash__(self) -> int:
        return Node.__hash__(self)

    def __eq__(self, other: Union[Lexicon, Context]) -> bool:
        if isinstance(other, Lexicon):
            return self.lexicon == other
        return other is self

    def __ne__(self, other: Union[Lexicon, Context]) -> bool:
        if isinstance(other, Lexicon):
            return self.lexicon != other
        return other is not self

    @overload
    def __getitem__(self, item: int) -> TokenOrContext: ...

    @overload
    def __getitem__(self, item: slice) -> List[TokenOrContext]: ...

    def __getitem__(self, item: Union[int, slice]) -> Union[TokenOrContext, List[TokenOrContext]]:
        """Return the child at the given index."""
        return super().__getitem__(item)  # type: ignore - this is fine, we inherit from list - SP

    # @property - Properties typically return something, converted to a function - SP
    def ls(self):
        """List the contents of this Context, for debugging purposes."""
        for i, n in enumerate(self):
            print("[{}] {}".format(i, repr(n)))

    def copy(self, parent: Context = None) -> Self:
        """Return a copy of the context, but with the specified parent.

        Reworked to improve type checking. - SP
        """
        # a non-recursive implementation due to Python's recursion limits
        copy_root = type(self)(self.lexicon, parent)

        current_original: Context = self
        current_copy: Context = copy_root
        i = 0

        while True:
            z = len(current_original)
            while i < z:
                m: TokenOrContext = current_original[i]  

                if isinstance(m, Context):
                    # We found a branch. Create a new context and dive in.
                    new_context = type(m)(m.lexicon, current_copy)
                    current_copy.append(new_context)

                    current_copy = new_context
                    current_original = m
                    i = 0
                    break
                else:
                    # It's a Token. Just copy it and stay on this level.
                    current_copy.append(m.copy(current_copy))
                    i += 1
            else:
                # We finished all children at this level. Can we go back up?
                if current_copy is copy_root:
                    break

                p_orig = current_original.parent
                p_copy = current_copy.parent
                assert p_orig is not None and p_copy is not None  # Both should have parents

                # Move "up" to the parents
                current_original = p_orig
                current_copy = p_copy
                # Set index to continue from where we left off
                i = len(current_copy)

        return copy_root  # type: ignore - this is fine, we return a Context, which is Self

    @property
    def pos(self) -> int:
        """Return the position or our first token. Returns 0 if empty."""
        try:
            node = self[0]
            while isinstance(node, Context):  # updated to appease typechecker - SP
                node = node[0]
            assert isinstance(node, Token)
            return node.pos
        except IndexError:
            return 0

    @property
    def end(self) -> int:
        """Return the end position or our last token. Returns 0 if empty."""
        try:
            node = self[-1]
            while isinstance(node, Context):  # updated to appease typechecker - SP
                node = node[-1]
            assert isinstance(node, Token)
            return node.end
        except IndexError:
            return 0

    def is_root(self) -> bool:
        """Return True if this Context has no parent node."""
        return self.parent is None

    def height(self) -> int:  # type: ignore - we always return an int - SP
        """Return the height of the tree (the longest distance to a descendant)."""
        if not self:
            return 0
        stack = []
        height = 0
        i = 0
        n: Context = self
        while True:
            for i in range(i, len(n)):
                m: TokenOrContext = n[i]  
                if m.is_context:
                    stack.append(i)
                    height = max(height, len(stack))
                    i = 0
                    n = m  # type: ignore - m is definitely a Context here - SP
                    break
            else:
                if stack:
                    p = n.parent
                    if p is None:
                        break  # This should not happen, but just in case - SP
                    n = p
                    i = stack.pop() + 1
                else:
                    return height + 1

    def tokens(self, reverse: bool = False) -> Iterable[Token]:
        """Yield all Tokens, descending into nested Contexts.

        If ``reverse`` is set to True, yield all tokens in backward direction.

        """
        children = reversed if reverse else iter
        stack = []
        gen: Iterator = children(self)
        while True:
            for n in gen:
                if n.is_token:
                    assert isinstance(n, Token)
                    yield n
                else:
                    stack.append(gen)
                    gen = children(n)
                    break
            else:
                if stack:
                    gen = stack.pop()
                else:
                    break

    def first_token(self) -> Optional[Token]:
        """Return our first Token."""
        try:
            node = self[0]
            while isinstance(node, Context):  # updated to appease typechecker - SP
                node = node[0]
            assert isinstance(node, Token)
            return node
        except IndexError:
            pass

    def last_token(self) -> Optional[Token]:
        """Return our last token."""
        try:
            node = self[-1]
            while isinstance(node, Context):  # updated to appease typechecker - SP
                node = node[-1]
            assert isinstance(node, Token)
            return node
        except IndexError:
            pass

    def find(self, pos: int) -> int:
        """Return the index of our child at (or to the right of) pos.

        Returns -1 if there is no such child.

        """
        i = 0
        hi = l = len(self)
        while i < hi:
            mid = (i + hi) // 2
            n: TokenOrContext = self[mid]  
            if n.end <= pos:
                i = mid + 1
            else:
                hi = mid
        return -1 if i == l else i

    def find_context(self, pos: int) -> Context:
        """Return the youngest Context at position (or self).

        Refactored to improve type checking. - SP
        """
        current_ctx: Context = self
        i = current_ctx.find(pos)
        while i != -1:
            child = current_ctx[i]
            # If it's a context and within range, go deeper
            if isinstance(child, Context) and child.pos <= pos:
                current_ctx = child
                i = current_ctx.find(pos)
            else:
                # It's a Token or the position doesn't match, stop here
                break
        return current_ctx

    def find_token(self, pos: int) -> Optional[Token]:
        """Return the Token at or to the right of position.

        Returns None if there is no such token.

        Refactored to improve type checking. - SP
        """
        i = self.find(pos)
        if i == -1:
            return None

        # Start with the child found at this level
        current_node: TokenOrContext = self[i]  

        # If it's a context, we need to go deeper until we find a token
        while isinstance(current_node, Context):
            i = current_node.find(pos)
            if i == -1:
                return None  # No token found in this context (shouldn't happen)
            current_node = current_node[i]  

        # At this point, current_node should be a Token
        assert isinstance(current_node, Token)
        return current_node

    def find_token_with_trail(self, pos: int) -> Tuple[Optional[Token], Optional[IndexTrail]]:
        """Return the Token at or to the right of position, and the trail of indices.

        The trail is the list of indices where the token was found. Returns
        (None, None) if there is no such token. Here is an example::

            >>> import parce
            >>> tree = parce.root(parce.find('css'), open('parce/themes/default.css').read())
            >>> tree.find_token_with_trail(600)
            (<Token ' Selected te...ow has focus ' at 566:607 (Comment)>, [21, 0])
            >>> tree[21][0]
            <Token ' Selected te...ow has focus ' at 566:607 (Comment)>

        """
        i = self.find(pos)
        if i == -1:
            return None, None

        # Start with the child found at the root level
        current_node: TokenOrContext = self[i]  
        trail: IndexTrail = [i]

        # Dive into contexts while tracking the indices
        while isinstance(current_node, Context):
            i = current_node.find(pos)
            if i == -1:
                return None, None  # No token found in this context (shouldn't happen)
            trail.append(i)
            current_node = current_node[i]

        # At this point, current_node should be a Token
        if isinstance(current_node, Token):
            return current_node, trail
        return None, None  # Again, this shouldn't happen, but just in case - SP

    def find_left(self, pos: int) -> int:
        """Return the index of our child at or to the left of pos.

        Returns -1 if there is no such child.

        """
        i = 0
        hi = len(self)
        while i < hi:
            mid = (i + hi) // 2
            n = self[mid]
            if n.pos < pos:
                i = mid + 1
            else:
                hi = mid
        return i - 1

    def find_token_left(self, pos: int) -> Optional[Token]:
        """Return the Token at or to the left of position.

        Returns None if there is no such token.

        Reworked for typechecker friendliness. - SP
        """
        i = self.find_left(pos)
        if i == -1:
            return None

        # Start with the child found at this level
        current_node: TokenOrContext = self[i]

        # If it's a context, we need to go deeper until we find a token
        while isinstance(current_node, Context):
            i = current_node.find_left(pos)
            if i == -1:
                return None  # No token found in this context (shouldn't happen)
            current_node = current_node[i]

        # At this point, current_node should be a Token
        assert isinstance(current_node, Token)
        return current_node

    def find_token_left_with_trail(self, pos: int) -> Tuple[Optional[Token], Optional[IndexTrail]]:
        """Return the Token at or to the left of position, and the trail of indices.

        Returns (None, None) if there is no such token.

        Reworked for typechecker friendliness. - SP
        """
        i = self.find_left(pos)
        if i == -1:
            return None, None

        # Start with the child found at the root level
        current_node: TokenOrContext = self[i]
        trail: IndexTrail = [i]

        # Dive into contexts while tracking the indices
        while isinstance(current_node, Context):
            i = current_node.find_left(pos)
            if i == -1:
                return None, None  # No token found in this context (shouldn't happen)
            trail.append(i)
            current_node = current_node[i]

        # At this point, current_node should be a Token
        if isinstance(current_node, Token):
            return current_node, trail
        return None, None  # Again, this shouldn't happen, but just in case - SP

    def find_token_after(self, pos: int) -> Optional[Token]:
        """Return the first token completely right from pos.

        Returns None if there is no token right from pos.

        Refactored for typechecker friendliness. - SP
        """
        node = self
        while isinstance(node, Context):
            i = 0
            hi = l = len(node)
            while i < hi:
                mid = (i + hi) // 2
                n = node[mid]

                # If it's a context, we need its very first token
                # to check if this entire branch starts after 'pos'.
                if isinstance(n, Context):
                    first = n.first_token()
                    # if the context is empty or starts at/before pos, we
                    # can skip it and check the next element
                    compare_pos = first.pos if first else n.pos
                else:
                    compare_pos = n.pos

                # Now, we want the first token where its position is > pos.
                # If this node's starting position is <= pos, it's not the target.
                if compare_pos <= pos:
                    i = mid + 1
                else:
                    hi = mid

            if i >= l:
                return

            node = node[i]
            if isinstance(node, Token):
                return node

    def find_token_before(self, pos: int) -> Optional[Token]:
        """Return the last token completely left from pos.

        Returns None if there is no token left from pos.

        Refactored for typechecker friendliness. - SP
        """
        node = self
        while isinstance(node, Context):
            i = 0
            hi = len(node)
            while i < hi:
                mid = (i + hi) // 2
                n = node[mid]
                if isinstance(n, Context):
                    last = n.last_token()
                    compare_pos = last.end if last else n.end
                else:
                    compare_pos = n.end
                if compare_pos <= pos:
                    i = mid + 1
                else:
                    hi = mid
            if i == 0:
                return
            node = node[i-1]
            if isinstance(node, Token):
                return node

    def range(self, start: int = 0, end: Optional[int] = None) -> Optional[Range]:
        """Return a :class:`Range`.

        The ancestor of the range is the common ancestor of the tokens found at
        start and end (or the context itself if start or end fall outside this
        context). If start is 0 and end is None, the range encompasses the full
        context.

        Returns None if this context is empty.

        """
        return Range.from_tree(self, start, end)


class Range:
    """A Range denotes a range of a tree structure.

    A range is defined by an ancestor context and possibly empty lists pointing
    to the start and end token, if specified. If both trails are not specified,
    the range encompasses the full context.

    """
    def __init__(
        self,
        ancestor: Context,
        start_trail: IndexTrail = None,
        end_trail: IndexTrail = None
    ):
        self.ancestor: Context = ancestor                   #: The specified ancestor
        self.start_trail: IndexTrail = start_trail or []    #: The specified start trail (empty list by default)
        self.end_trail: IndexTrail = end_trail or []        #: The specified end trail (empty list by default)

    def __repr__(self) -> str:
        return "<{} {} [{}:{}]>".format(
            type(self).__name__, self.ancestor.lexicon, self.pos, self.end
        )

    @property
    def pos(self) -> int:
        """
        The position of the first token in our range.

        Reworked for typechecker friendliness. - SP
        """
        node = self.ancestor
        for i in self.start_trail:
            if isinstance(node, Context):
                node = node[i]
            else:
                break
        return node.pos

    @property
    def end(self) -> int:
        """
        The end position of the last token in our range.

        Reworked for typechecker friendliness. - SP
        """
        node = self.ancestor
        for i in self.end_trail:
            if isinstance(node, Context):
                node = node[i]
            else:
                break
        return node.end

    @classmethod
    def from_tree(cls, tree: Context, start: int = 0, end: Optional[int] = None) -> Optional[Range]:
        """Create a Range.

        The ancestor is the common ancestor of the tokens found at start and
        end (or the tree itself if start or end fall outside the range of the
        tree). If start is 0 and end is None, the range encompasses the full
        tree.

        Returns None if the tree is empty.

        TODO: There are several typing issues here that I haven't been able to resolve cleanly,
              should address them at some point. - SP
        """
        if not tree:
            return  # empty

        context = tree
        if end is not None and end < tree.end:
            if end <= start:
                return
            end_trail = tree.find_token_left_with_trail(end)[1]
            if not end_trail:
                return
        else:
            end_trail = []
        if start > 0:
            start_trail = tree.find_token_with_trail(start)[1]
            if not start_trail:
                return
            if end_trail:
                # find the youngest common ancestor
                n = 0  # Added to appease typechecker - SP
                for n, (i, j) in enumerate(zip(start_trail, end_trail)):
                    assert isinstance(context, Context)
                    if i != j or isinstance(context[i], Token):
                        break
                    context = context[i]
                if n:
                    del start_trail[:n]
                    del end_trail[:n]
        else:
            start_trail = []

        assert isinstance(context, Context)
        return cls(context, start_trail, end_trail)

    def slices(self, target_factory: Optional[TargetFactory] = None) -> Iterable[Tuple[Context, slice]]:
        """Yield (context, slice) tuples.

        The yielded slices include the tokens at the end of start and end
        trail.

        If you specify a ``target_factory``, it should be a
        :class:`~.target.TargetFactory` object, and it will be updated along
        with the yielded slices.

        Refactored for typechecker and readability improvements. - SP
        """
        if self.start_trail:
            start_idx = self.start_trail[0]
            if len(self.start_trail) > 1:
                ancestors = []
                current_node = self.ancestor[start_idx]
                assert isinstance(current_node, Context)  # added to appease typechecker - SP

                for trail_idx in self.start_trail[1:]:
                    ancestors.append((current_node, trail_idx))
                    n = current_node[trail_idx]

                # Yield the deepest context first (the one containing the start token)
                parent, last_idx = ancestors[-1]
                yield parent, slice(last_idx, None)

                # Walk back up the trail
                for p, i in ancestors[-2::-1]:
                    if target_factory:
                        target_factory.pop()
                    yield p, slice(i + 1, None)

                if target_factory:
                    target_factory.pop()
                start_idx += 1
        else:
            start_idx = 0

        if self.end_trail:
            end_root_idx = self.end_trail[0]

            if len(self.end_trail) == 1:
                # Simple case: start and end are in the same root context
                yield self.ancestor, slice(start_idx, end_root_idx + 1)
            else:
                # More complex case: end is deeper in the tree
                yield self.ancestor, slice(start_idx, end_root_idx)

                current_node = self.ancestor[end_root_idx]
                assert isinstance(current_node, Context)  # added to appease typechecker - SP

                for sub_idx in self.end_trail[1:-1]:
                    if target_factory and isinstance(current_node, Context):
                        target_factory.push(current_node.lexicon)
                    assert isinstance(current_node, Context)
                    yield current_node, slice(sub_idx)
                    current_node = current_node[sub_idx]

                # Yield the deepest context last (the one containing the end token)
                if target_factory and isinstance(current_node, Context):
                    target_factory.push(current_node.lexicon)
                assert isinstance(current_node, Context)
                yield current_node, slice(self.end_trail[-1] + 1)
        else:
            yield self.ancestor, slice(start_idx, None)

    def tokens(self) -> Iterator[Token]:
        """Yield all tokens in this range.

        The first and last tokens may overlap with the start and end positions.

        """
        for context, slice_ in self.slices():
            yield from util.tokens(context[slice_])

def make_tokens(
    lexemes: Sequence[Lexeme],
    parent: Optional[Context] = None
) -> Tuple[Token, ...]:
    """Factory returning a tuple of one or more :class:`Token` instances for
    the lexemes.

    The ``lexemes`` argument is an iterable of three-tuples like the
    ``lexemes`` in an :class:`~parce.lexer.Event` namedtuple defined in the
    :mod:`~parce.lexer` module. If there is more than one lexeme,
    :class:`GroupToken` instances are created.

    The specified ``parent`` context is set as parent, if given.

    """
    if len(lexemes) > 1:
        return GroupToken.make_group(parent, lexemes)
    else:
        return Token(parent, *lexemes[0]),
