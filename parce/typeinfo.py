from __future__ import annotations

from typing import TYPE_CHECKING, Tuple, Literal, Union

if TYPE_CHECKING:
    from .standardaction import StandardAction


# Literal collections
_CommonEncodings = Literal[
    "utf-8",
    "utf-16",
    "latin-1",
    "ascii",
    "cp1252"
]

_CommonMimeTypes = Literal[
    # Text
    "text/plain",
    "text/x-lilypond",     # The standard for .ly files
    "text/html",
    "text/css",
    "text/markdown",

    # Data Formats
    "application/json",
    "application/xml",
    "application/pdf",     # Common LilyPond output

    # Images
    "image/png",
    "image/jpeg",
    "image/svg+xml",       # Common LilyPond vector output
    "image/webp",

    # Audio/Music
    "audio/midi",          # LilyPond MIDI output
    "audio/mpeg",
    "audio/ogg",
    "audio/wav"
]

Encoding = Union[_CommonEncodings, str]
MimeType = Union[_CommonMimeTypes, str]

Lexeme = Tuple[int, str, StandardAction]
