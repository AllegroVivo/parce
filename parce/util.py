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
Various utility classes and functions.

This module only depends on the Python standard library.

"""
from __future__ import annotations

import bisect
import codecs
import contextlib
import functools
import os.path
import sys
import threading
from collections.abc import Callable, Iterator, Iterable, Sequence
from contextlib import AbstractContextManager
from types import FunctionType, MethodType, TracebackType
from typing import Any, TYPE_CHECKING, cast, Self
from weakref import WeakKeyDictionary, WeakMethod

if TYPE_CHECKING:
    from parce.tree import Token, Node, Context
    from parce.language import Language
    from parce._types import ContextOrToken

type DispatcherTable = dict[Any, Callable[..., Any]]

class Dispatcher:
    """Dispatches calls via an instance to methods based on the first argument.

    A Dispatcher is used as a decorator when defining a class, and then called
    via or in an instance to select a method based on the first argument (which
    must be hashable).

    If you override methods in a subclass that were dispatched, the
    dispatcher automatically dispatches to the new method. If you want to add
    new keywords in a subclass, just create a new Dispatcher with the same
    name. It will automatically inherit the references stored in the old
    dispatcher.

    Usage::

        class MyClass:
            dispatch = Dispatcher()

            @dispatch(1)
            def call_one(self, value):
                print("One called", value)

            @dispatch(2)
            def call_two(self, value):
                print("Two called", value)

            def handle_input(self, number, value):
                self.dispatch(number, value)

        >>> i = MyClass()
        >>> i.handle_input(2, 3)
        Two called 3

    Values of the first argument that are not handled are normally silently
    ignored, but you can also specify a default function, that is called when
    a value is not handled::

        class MyClass:
            @Dispatcher
            def dispatch(self, number, value):
                print("Default function called:", number, value)

            @dispatch(1)
            def call_one(self, value):
                print("One called", value)

            @dispatch(2)
            def call_two(self, value):
                print("Two called", value)

            def handle_input(self, number, value):
                self.dispatch(number, value)

        >>> i = MyClass()
        >>> i.handle_input(3, 10)
        Default function called: 3 10

    To get the method for a key without calling it directly, e.g. to see of
    a method exists for a key, use::

        >>> meth = i.dispatch.get(1)   # returns a bound method
        >>> if meth:
        ...     meth("hi there")
        ...
        One called hi there

    If you specified a default method on creation of the dispatcher, that
    method is also accessible, in the ``default`` attribute::

        >>> i.dispatch.default(1, 2)
        Default function called: 1 2

    """
    _name: str

    def __init__(self, default_func: Callable[..., Any] | None = None) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._table: dict[Any, str] = {}
        self._tables: WeakKeyDictionary[type[Any], DispatcherTable] = WeakKeyDictionary()
        self._default_func: Callable[..., Any] | None = default_func

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self._name = name

    def __call__[F: Callable[..., Any]](self, *args: Any) -> Callable[[F], F]:
        def decorator(func: F) -> F:
            for a in args:
                self._table[a] = func.__name__
            return func
        return decorator

    def __get__(self, instance: object, owner: type[Any]) -> _Dispatcher:
        try:
            table = self._tables[owner]
        except KeyError:
            with self._lock:
                try:
                    table = self._tables[owner]
                except KeyError:
                    # find Dispatchers in base classes with the same name
                    # if found, inherit their references
                    dispatchers = []
                    for c in owner.mro():
                        d = c.__dict__.get(self._name)
                        if type(d) is type(self):
                            dispatchers.append(d)
                    _table = {}
                    for d in reversed(dispatchers):
                        _table.update(d._table)
                    # now, store the actual functions instead of their names
                    table = self._tables[owner] = {a: getattr(owner, name)
                                for a, name in _table.items()}
        return _Dispatcher(self, table, instance, owner)


class _Dispatcher:
    """Helper class for Dispatcher."""
    __slots__ = ("_dispatcher", "_table", "_instance", "_owner")

    def __init__(
        self,
        dispatcher: Dispatcher,
        table: DispatcherTable,
        instance: Any,
        owner: type[Any]
    ):
        self._dispatcher: Dispatcher = dispatcher
        self._table: DispatcherTable = table
        self._instance: Any = instance
        self._owner: type[Any] = owner

    def __repr__(self) -> str:
        return "<{}.{} {}.{} of {}>".format(
            self._dispatcher.__class__.__module__,
            self._dispatcher.__class__.__name__,
            self._owner.__name__,
            self._dispatcher._name,
            repr(self._instance))

    def __call__(self, key: Any, *args: Any, **kwargs: Any) -> Any:
        """Call the stored method based on the key (first argument) with the
        other arguments."""
        f = self._table.get(key)
        if f:
            return f(self._instance, *args, **kwargs)
        f = self.default
        if f:
            return f(key, *args, **kwargs)

    @property
    def default(self) -> Callable[..., Any] | None:
        """The bound method specified as default, if any."""
        f = self._dispatcher._default_func
        if f:
            return f.__get__(self._instance, self._owner)
        return None

    def get(self, key: Any) -> Any:
        """Return the bound method for the key, without calling it."""
        f = self._table.get(key)
        if f:
            return f.__get__(self._instance, self._owner)
        return None

type FunctionOrMethod = Callable[..., Any]

class _Observer:
    """Helper for Observable class.

    The magic lt/gt methods are to help with sorting on priority and the eq/ne
    methods to see if the function already is added to the list of slots.

    """
    __slots__ = ('func', 'once', 'priority', 'call')

    def __init__(
        self,
        func: FunctionOrMethod,
        once: bool | None = None,
        prepend_self: bool = False,
        priority: int = 0
    ):
        self.func: FunctionOrMethod | WeakMethod[MethodType]
        self.call: Callable[..., Any]
        if isinstance(func, MethodType):
            self.func = WeakMethod(func)
            self.call = self.call_weakmethod_with_self if prepend_self else self.call_weakmethod
        else:
            self.func = func
            self.call = func if prepend_self else self.call_func
        self.once: bool | None = once
        self.priority: int = priority

    def __repr__(self) -> str:
        return "<Observer for {}>".format(self.func)

    def __eq__(self, other: object) -> bool:
        if type(other) is _Observer:
            return self.func == other.func
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        if type(other) is _Observer:
            return self.func != other.func
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if type(other) is _Observer:
            return self.priority < other.priority
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if type(other) is _Observer:
            return self.priority > other.priority
        return NotImplemented

    def call_func(self, observable: Observable, *args: Any, **kwargs: Any) -> Any:
        return self.func(*args, **kwargs)

    def call_weakmethod(self, observable: Observable, *args: Any, **kwargs: Any) -> None:
        func = self.func()
        if func:
            return func(*args, **kwargs)
        self.once = True

    def call_weakmethod_with_self(self, observable: Observable, *args: Any, **kwargs: Any) -> None:
        func = self.func()
        if func:
            return func(observable, *args, **kwargs)
        self.once = True


class Observable:
    """Simple base class for objects that need to announce events.

    Use :meth:`connect` to add a callable to be called when a certain event
    occurs.

    To announce an event from inside methods, use :meth:`emit`. In your
    documentation you should specify *which* arguments are used for *which*
    events; in order to keep this class simple and fast, no checking is
    performed whatsoever.

    Example::

        >>> o = Observable()
        >>>
        >>> def slot(arg):
        ...     print("slot called:", arg)
        ...
        >>> o.connect('test', slot)
        >>>
        >>> o.emit('test', 1)   # in a method of your Observable subclass
        slot called: 1

    It is also possible to use :meth:`emit` in a :ref:`with <with>` context. In
    that case the return values of the connected functions are collected and if
    they are a context manager, they are entered as well. An example::

        >>> import contextlib
        >>>
        >>> @contextlib.contextmanager
        ... def f():
        ...     print("one")
        ...     yield
        ...     print("two")
        ...
        >>> o=Observable()
        >>> o.connect('test', f)
        >>>
        >>> with o.emit('test'):
        ...     print("Yo!!!")
        ...
        one
        Yo!!!
        two

    This enables you to announce events, and connected objects can perform a
    task before the event's context starts and another task when the event's
    context exits.

    """
    def __init__(self) -> None:
        self._callbacks: dict[str, list[_Observer]] = {}

    def connect(
        self,
        event: str,
        func: FunctionOrMethod,
        once: bool = False,
        prepend_self: bool = False,
        priority: int = 0
    ) -> None:
        """Register a function to be called when a certain event occurs.

        The ``event`` should be a string or any hashable object that identifies
        the event. The ``priority`` determines the order the functions are
        called. Lower numbers are called first. If ``once`` is set to True, the
        function is called once and then removed from the list of callbacks. If
        ``prepend_self`` is True, the callback is called with the observable
        itself as first argument.

        If the ``func`` is a method, it is stored using a weak reference.

        """
        observer = _Observer(func, once, prepend_self, priority)
        slots = self._callbacks.setdefault(event, [])
        if observer not in slots:
            bisect.insort_right(slots, observer)

    def disconnect(self, event: str, func: FunctionOrMethod) -> None:
        """Remove a previously registered callback function."""
        try:
            slots = self._callbacks[event]
        except KeyError:
            return
        observer = _Observer(func)
        try:
            slots.remove(observer)
        except ValueError:
            return
        if not slots:
            del self._callbacks[event]

    def disconnect_all(self, event: str | None = None) -> None:
        """Disconnect all functions (from the event).

        If event is None, disconnects all connected functions from all events.

        """
        if event is None:
            self._callbacks.clear()
        else:
            try:
                del self._callbacks[event]
            except KeyError:
                pass

    def has_connections(self, event: str) -> bool:
        """Return True when there is at least one callback registered for the event.

        This can be used before performing some task, the task maybe then can
        be optimized because we know nobody needs the events.

        """
        return event in self._callbacks

    def is_connected(self, event: str, func: FunctionOrMethod) -> bool:
        """Return True if func is connected to event."""
        try:
            slots = self._callbacks[event]
        except KeyError:
            return False
        return _Observer(func) in slots

    def emit(self, event: str, *args: Any, **kwargs: Any) -> contextlib.ExitStack[bool | None]:
        """Call all callbacks for the event.

        Returns a :class:`contextlib.ExitStack` instance. When any of the
        connected callbacks returns a context manager, that context is entered,
        and added to the exit stack, so it is exited when the exit stack is
        exited.

        """
        s = contextlib.ExitStack()
        try:
            slots = self._callbacks[event]
        except KeyError:
            return s
        disconnect = []
        for i, observer in enumerate(slots):
            result = observer.call(self, *args, **kwargs)
            try:
                s.enter_context(result)
            except Exception:
                pass
            if observer.once:
                disconnect.append(i)
        if disconnect:
            for i in reversed(disconnect):
                del slots[i]
            if not slots:
                del self._callbacks[event]
        return s


class Switch:
    """A context manager that evaluates to True when in a context, else to False.

    Example::

        clicking = Switch()

        def myfunc():
            with clicking:
                blablabl()

        # and elsewhere:
        def blablabl():
            if not clicking:
                do_something()

        # when blablabl() is called from myfunc, clicking evaluates to True,
        # so do_something() is not called then.

    A Switch can also be used in a class definition; via the descriptor
    protocol it will then create per-instance Switch objects which will be
    stored using a weak reference to the instance. For example::

        class MyClass:
            clicking = Switch()

            def click_event(self, event):
                with self.clicking:
                    self.blablabla()

            def blablabla(self):
                do_something()
                if not self.clicking:
                    # this only runs when blablabla() was not called
                    # from click_event()
                    update_something()


    """
    __slots__ = ('_value',)

    _value: int | WeakKeyDictionary[Any, Switch]

    def __init__(self) -> None:
        self._value = 0

    def __enter__(self) -> None:
        assert isinstance(self._value, int)
        self._value += 1

    def __exit__(
        self,
        exc_type: type[BaseException],
        exc_val: BaseException | None,
        exc_tb: TracebackType
    ) -> None:
        assert isinstance(self._value, int)
        self._value -= 1

    def __bool__(self) -> bool:
        return bool(self._value)

    def __get__(self, instance: Any, owner: type[Any]) -> Switch:
        try:
            return self._value[instance]  # type: ignore[index]  # int until first use
        except TypeError:
            # value still was 0, replace it with a weakref dict
            self._value = WeakKeyDictionary()
        except KeyError:
            pass
        assert not isinstance(self._value, int)
        s = self._value[instance] = type(self)()
        return s


def object_locker() -> Callable[[object], AbstractContextManager[Any]]:
    """Return a callable that can hold a lock on an object.

    The Lock is automatically created when requested for the first time, and
    deleted when released for the last time. Keeps a reference to the object
    until the last lock is released.

    Usage example::

        >>> lock = object_locker()
        >>> with lock(obj):
        ...     do_something()

    The lock callable should remain alive as long as the object is alive, so it
    is reused; it is the context where the locking is active. This function is
    an alternative to::

        >>> class Object:
        ...     def __init__(self):
        ...         self._lock = threading.Lock()
        ...
        >>> o = Object()

    and then later::

        >>> with o._lock:
        ...     do_something()

    In this use case the allocated Lock lives as long as the object, which
    might not be desirable if you have a large amount of objects of this type.

    """
    locker: dict[object, threading.Lock] = {}
    locker_lock = threading.Lock()

    def lock_object(obj: object) -> AbstractContextManager[Any]:
        with locker_lock:
            try:
                return locker[obj]
            except KeyError:
                lock = locker[obj] = threading.Lock()
                @contextlib.contextmanager
                def cleanup() -> Iterator[None]:
                    try:
                        with lock:
                            yield
                    finally:
                        del locker[obj]
                return cleanup()
    return lock_object


def cached_method[F: Callable[..., Any]](func: F) -> F:
    """Wrap a method and caches its return value.

    The method argument tuple should be hashable. Keyword arguments are not
    supported. The cache is thread-safe. Does not keep a reference to the
    instance.

    """
    lock = object_locker()
    cache: WeakKeyDictionary[Any, dict[tuple[Any, ...], Any]] = WeakKeyDictionary()

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any) -> Any:
        with lock(self):
            try:
                return cache[self][args]
            except KeyError:
                v = cache.setdefault(self, {})[args] = func(self, *args)
                return v
    return cast("F", wrapper)


def cached_property(func: Callable[..., Any]) -> property:
    """Like property, but caches the computed value."""
    return property(cached_method(func))


def cached_func[F: Callable[..., Any]](func: F) -> F:
    """Wrap a normal function and caches the return value.

    The function's argument tuple should be hashable; keyword arguments are not
    supported. The cache is thread-safe.

    """
    cache = caching_dict(func, True)
    @functools.wraps(func)
    def wrapper(*args: Any) -> Any:
        return cache[args]
    return cast("F", wrapper)


def caching_dict(
    func: Callable[..., Any],
    unpack: bool = False,
    cache_none: bool = True
) -> dict[Any, Any]:
    """Create a dict with a thread-safe factory function for missing keys.

    When a key is not present, the factory function is called. The difference
    with :class:`collections.defaultdict` is that the factory function is
    called with the key as argument, or, if ``unpack`` is set to True, with the
    key arguments unpacked. Built-in locking makes sure another thread cannot
    call the factory function at the same time.

    If ``cache_none`` is set to False and the function returns None, that
    result is not cached, meaning that the function is run again on the next
    request.

    """
    lock = threading.Lock()

    if unpack:
        if cache_none:
            def result(self: Any, key: Any) -> Any:
                value = self[key] = func(*key)
                return value
        else:
            def result(self: Any, key: Any) -> Any:
                value = func(*key)
                if value is not None:
                    self[key] = value
                return value
    elif cache_none:
        def result(self: Any, key: Any) -> Any:
            value = self[key] = func(key)
            return value
    else:
        def result(self: Any, key: Any) -> Any:
            value = func(key)
            if value is not None:
                self[key] = value
            return value

    class cache(dict):
        def __getitem__(self, key: Any) -> Any:
            with lock:
                try:
                    return super().__getitem__(key)
                except KeyError:
                    return result(self, key)
    return cache()


def file_cache(func: Callable[[str], Any]) -> dict[str, Any]:
    """Return a dict that caches the factory function results.

    The function should accept one argument which is assumed to be a filename.
    The result value is cached, but not returned anymore when the mtime of the
    file has changed; in that case the function is called again. If the mtime
    of the file can't be determined the function result is not cached.

    """
    lock = threading.Lock()

    class filecache(dict):
        def __getitem__(self, key: str) -> Any:
            with lock:
                try:
                    mtime, value = super().__getitem__(key)
                except KeyError:
                    mtime = -1
                try:
                    new_mtime = os.path.getmtime(key)
                except OSError:
                    new_mtime = -2
                if mtime != new_mtime:
                    value = func(key)
                    if new_mtime >= 0:
                        self[key] = new_mtime, value
                return value  # type: ignore[possibly-undefined]  # mtime -1 never equals a real mtime
    return filecache()


class Symbol:
    """A unique object that has a name; the same name returns the same object."""
    _name: str

    def __repr__(self) -> str:
        return self._name

    @cached_func
    def __new__(cls, name: str) -> Symbol:
        obj = object.__new__(cls)
        obj._name = name
        return obj


def fix_boundaries(stream: Iterable[Any], start: int, end: int | None) -> Iterator[Any]:
    """Yield all items from the stream of tuples.

    The first two items of each tuple are regarded as pos and end. This
    function adjusts the pos of the first item and the end of the last item so
    that they do not stick out of the range start..end. If the pos of the first
    item is below start, it is set to start; if the end of the last item is
    beyond end, it is set to end.

    If start == 0, the first item will never be adjusted; if end is None, the
    last item will not be adjusted.

    """
    if start == 0 and end is None:
        yield from stream   # do nothing
    else:
        stream = iter(stream)
        for i in stream:
            if i[0] < start:
                i = type(i)((start, i[1], *i[2:]))
            for j in stream:
                yield i
                i = j
            if end is not None and i[1] > end:
                i = type(i)((i[0], end, *i[2:]))
            yield i

def _tuple(*args: Any) -> tuple[Any, ...]:
    """Return the arguments as a tuple.

    This is the ideal default factory for merge_adjacent().

    """
    return args


def merge_adjacent(
    stream: Iterable[Any],
    factory: Callable[..., Any] = _tuple
) -> Iterator[Any]:
    """Yield items from a stream of tuples.

    The first two items of each tuple are regarded as pos and end.
    If they are adjacent, and the rest of the tuples compares the same,
    the items are merged.

    Instead of the default factory, which yields plain tuples, you can give a
    named tuple or any other type to wrap the streams items in.

    """
    stream = iter(stream)
    for pos, end, *rest in stream:
        for npos, nend, *nrest in stream:
            if nrest != rest or npos > end:
                yield factory(pos, end, *rest)
                pos, rest = npos, nrest
            end = nend
        yield factory(pos, end, *rest)


def merge_adjacent_actions(tokens: Iterable[Token]) -> Iterator[Any]:
    """Yield three-tuples (pos, end, action).

    Adjacent actions that are the same are merged into
    one range.

    """
    return merge_adjacent((t.pos, t.end, t.action) for t in tokens)


def merge_adjacent_actions_with_language(tokens: Iterable[Token]) -> Iterator[Any]:
    """Yield four-tuples (pos, end, action, language).

    Adjacent actions that are the same and occurred in the same language
    are merged into one range.

    """
    return merge_adjacent(
        (t.pos, t.end, t.action, t.parent.lexicon.language)  # type: ignore[union-attr]  # tokens in a tree always have both
        for t in tokens
    )


def get_bom_encoding(data: bytes) -> tuple[str | None, bytes]:
    """Get the BOM (Byte Order Mark) of bytes ``data``, if any.

    A two-tuple is returned (encoding, data). If the data starts with a BOM
    mark, its encoding is determined and the BOM mark is stripped off.
    Otherwise, the returned encoding is None and the data is returned
    unchanged.

    """
    for bom, encoding in (
        (codecs.BOM_UTF8, 'utf-8'),
        (codecs.BOM_UTF16_LE, 'utf_16_le'),
        (codecs.BOM_UTF16_BE, 'utf_16_be'),
        (codecs.BOM_UTF32_LE, 'utf_32_le'),
        (codecs.BOM_UTF32_BE, 'utf_32_be'),
            ):
        if data.startswith(bom):
            return encoding, data[len(bom):]
    return None, data


def split_list[T](l: list[T], separator: T) -> Iterator[list[T]]:
    """Split list on items that compare equal to separator.

    Yields result lists that may be empty.

    """
    i = 0
    try:
        while True:
            j = l.index(separator, i)
            yield l[i:j]
            i = j + 1
    except ValueError:
        yield l[i:]


def unroll(obj: Any) -> Iterator[Any]:
    """Unroll a tuple or list.

    If the object is a tuple or list, yields the unrolled members recursively.
    Otherwise just the object itself is yielded.

    """
    if type(obj) in (tuple, list):
        stack = []
        gen = iter(obj)
        while True:
            for obj in gen:
                if type(obj) in (tuple, list):
                    stack.append(gen)
                    gen = iter(obj)
                    break
                else:
                    yield obj
            else:
                if stack:
                    gen = stack.pop()
                else:
                    break
    else:
        yield obj


def tokens(nodes: Sequence[ContextOrToken], reverse: bool = False) -> Iterator[Token]:
    """Helper to yield tokens from the iterable of nodes.

    If ``reverse`` is set to True, yields the tokens of the nodes in backward
    direction.

    """
    if reverse:
        nodes: Iterable[ContextOrToken] = reversed(nodes)  # type: ignore[no-redef]
    for n in nodes:
        if n.is_token:
            yield n
        else:
            yield from n.tokens(reverse)


def language_sister_class[L: Language, T](
    language: type[L],
    template: str,
    base: type[T],
    try_parents: bool = False
) -> type[T] | None:
    """Find a ``language`` sister class in the same module, with a name that
    matches the ``template``, and which is a subclass of ``base``.

    If ``try_parents`` is True, the parent classes of the language class are
    checked if a sister class is not found.

    The template string should contain ``{}``, which is replaced with the
    language's class name. Returns None if no sister class is defined.
    Example::

        >>> from parce.util import language_sister_class
        >>> from parce.lang.json import Json
        >>> from parce.transform import Transform
        >>> language_sister_class(Json, "{}Transform", Transform)
        <class 'parce.lang.json.JsonTransform'>

    """
    langs = language.mro()[:-2] if try_parents else [language]
    for l in langs:
        module = sys.modules[l.__module__]
        name = template.format(l.__name__)
        cls = getattr(module, name, None)
        if isinstance(cls, type) and issubclass(cls, base):
            return cls
    return None
