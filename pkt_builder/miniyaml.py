#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""miniyaml.py -- a small, dependency-free YAML subset parser.

Written for :mod:`pkt_builder` because the tool must run on a stock Python with
no ``pip install`` step (same rule as ``pkt_core``).  It supports exactly the
YAML this tool's config format uses:

* block mappings and block sequences (indentation based, ``-`` items)
* ``- key: value`` (a mapping that starts inside a sequence item)
* flow collections: ``[a, b]``, ``{k: v}`` and single-pair maps inside a flow
  sequence, i.e. ``[A, B, dce: A, clock: 64000]`` (legal YAML, and exactly the
  shape the pkt_builder link syntax uses)
* literal (``|``) and folded (``>``) block scalars, with ``-``/``+`` chomping
* single- and double-quoted scalars, **including multi-line ones**: their line
  breaks are kept as real newlines (stock PyYAML folds them into spaces, which
  silently destroys an IOS config)
* comments (``#``), booleans, integers, floats, ``null``/``~``

Everything else (anchors, aliases, tags, multiple documents, explicit keys)
raises :class:`YamlError` instead of being parsed half-way.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = ["load", "load_file", "YamlError"]


class YamlError(ValueError):
    """Raised for YAML the parser does not understand."""


_NULL = {"", "null", "Null", "NULL", "~"}
_TRUE = {"true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"}
_FALSE = {"false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF"}

_INT_RE = re.compile(r"[-+]?\d+")
_FLOAT_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?")


# --------------------------------------------------------------------------- #
# scalars
# --------------------------------------------------------------------------- #
def _scalar(text: str) -> Any:
    text = text.strip()
    if text in _NULL:
        return None
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    if _INT_RE.fullmatch(text):
        return int(text)
    if _FLOAT_RE.fullmatch(text):
        return float(text)
    return text


def _unescape(text: str, quote: str = '"') -> str:
    if quote == "'":
        return text.replace("''", "'")
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c != "\\" or i + 1 >= len(text):
            out.append(c)
            i += 1
            continue
        n = text[i + 1]
        out.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0",
                    '"': '"', "\\": "\\", "'": "'", "/": "/"}.get(n, "\\" + n))
        i += 2
    return "".join(out)


def _strip_comment(line: str) -> str:
    """Drop a trailing ``# comment`` that is not inside a quoted scalar."""
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
        i += 1
    return line.rstrip()


def _is_seq_item(content: str) -> bool:
    return content == "-" or content.startswith("- ")


def _split_key(content: str):
    """Split ``key: rest`` at the first top-level ``:`` (quote-aware)."""
    quote = None
    i = 0
    while i < len(content):
        c = content[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == ":" and (i + 1 == len(content) or content[i + 1] in " \t"):
            raw_key = content[:i].strip()
            if raw_key[:1] in ("'", '"') and raw_key[-1:] == raw_key[:1]:
                raw_key = _unescape(raw_key[1:-1], raw_key[0])
            return raw_key, content[i + 1:].strip()
        i += 1
    return None, None


def _looks_like_mapping(content: str) -> bool:
    if not content or content[0] in "[{\"'":
        return False
    key, _ = _split_key(content)
    return key is not None


# --------------------------------------------------------------------------- #
# flow collections
# --------------------------------------------------------------------------- #
class _Flow:
    def __init__(self, text: str):
        self.s = text
        self.i = 0

    def parse(self) -> Any:
        value = self._value()
        self._ws()
        if self.i != len(self.s):
            raise YamlError("trailing text in flow collection: %r" % self.s[self.i:])
        return value

    def _ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t\n":
            self.i += 1

    def _value(self) -> Any:
        self._ws()
        if self.i >= len(self.s):
            raise YamlError("unexpected end of flow collection")
        c = self.s[self.i]
        if c == "[":
            return self._seq()
        if c == "{":
            return self._map()
        if c in "\"'":
            return self._quoted(c)
        return _scalar(self._plain())

    def _seq(self):
        self.i += 1
        out = []
        while True:
            self._ws()
            if self.i >= len(self.s):
                raise YamlError("unterminated flow sequence")
            if self.s[self.i] == "]":
                self.i += 1
                return out
            out.append(self._item())
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
                continue
            if self.i < len(self.s) and self.s[self.i] == "]":
                self.i += 1
                return out
            raise YamlError("expected ',' or ']' in flow sequence")

    def _map(self):
        self.i += 1
        out = {}
        while True:
            self._ws()
            if self.i >= len(self.s):
                raise YamlError("unterminated flow mapping")
            if self.s[self.i] == "}":
                self.i += 1
                return out
            key = self._plain_key()
            self._ws()
            if self.i >= len(self.s) or self.s[self.i] != ":":
                raise YamlError("expected ':' in flow mapping")
            self.i += 1
            out[str(key)] = self._value()
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
                continue
            if self.i < len(self.s) and self.s[self.i] == "}":
                self.i += 1
                return out
            raise YamlError("expected ',' or '}' in flow mapping")

    def _item(self):
        """One flow-sequence entry: either a value or a single-pair mapping.

        ``[A, B, dce: A, clock: 64000]`` is legal YAML: the last two entries are
        single-pair mappings, not strings.
        """
        save = self.i
        if self.i < len(self.s) and self.s[self.i] not in "[{\"'":
            j = self.i
            while j < len(self.s) and self.s[j] not in ",:]}":
                j += 1
            if j < len(self.s) and self.s[j] == ":":
                key = _scalar(self.s[save:j])
                self.i = j + 1
                return {str(key): self._value()}
        self.i = save
        return self._value()

    def _plain_key(self) -> str:
        self._ws()
        if self.i < len(self.s) and self.s[self.i] in "\"'":
            q = self.s[self.i]
            return str(self._quoted(q))
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in ":,}]":
            self.i += 1
        return str(_scalar(self.s[start:self.i]))

    def _plain(self) -> str:
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in ",]}\n":
            self.i += 1
        return self.s[start:self.i]

    def _quoted(self, quote: str) -> str:
        self.i += 1
        start = self.i
        buf = []
        while self.i < len(self.s):
            c = self.s[self.i]
            if quote == '"' and c == "\\" and self.i + 1 < len(self.s):
                buf.append(c)
                buf.append(self.s[self.i + 1])
                self.i += 2
                continue
            if c == quote:
                if quote == "'" and self.i + 1 < len(self.s) and self.s[self.i + 1] == "'":
                    buf.append("''")
                    self.i += 2
                    continue
                self.i += 1
                return _unescape("".join(buf) or self.s[start:self.i - 1], quote)
            buf.append(c)
            self.i += 1
        raise YamlError("unterminated quoted scalar")


# --------------------------------------------------------------------------- #
# block parser
# --------------------------------------------------------------------------- #
class _Parser:
    def __init__(self, text: str):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if text.startswith("\ufeff"):
            text = text[1:]
        self.lines = text.split("\n")
        self.i = 0

    # -- helpers ---------------------------------------------------------- #
    @staticmethod
    def _indent(raw: str) -> int:
        n = 0
        while n < len(raw) and raw[n] == " ":
            n += 1
        if n < len(raw) and raw[n] == "\t":
            raise YamlError("tab character used for indentation")
        return n

    def _skip(self) -> None:
        while self.i < len(self.lines):
            content = _strip_comment(self.lines[self.i])
            if not content.strip():
                self.i += 1
                continue
            break

    def _cur(self):
        self._skip()
        if self.i >= len(self.lines):
            return None
        raw = self.lines[self.i]
        ind = self._indent(raw)
        return ind, _strip_comment(raw[ind:]).strip()

    # -- entry ------------------------------------------------------------ #
    def parse(self) -> Any:
        cur = self._cur()
        if cur is None:
            return None
        value = self._block(cur[0])
        cur = self._cur()
        if cur is not None:
            raise YamlError("line %d: unexpected content %r" % (self.i + 1, cur[1]))
        return value

    def _block(self, ind: int) -> Any:
        cur = self._cur()
        if cur is None or cur[0] < ind:
            return None
        if cur[0] > ind:
            raise YamlError("line %d: unexpected indent" % (self.i + 1))
        if _is_seq_item(cur[1]):
            return self._seq(ind)
        return self._map(ind)

    # -- mappings --------------------------------------------------------- #
    def _map(self, ind: int) -> dict:
        out: dict = {}
        while True:
            cur = self._cur()
            if cur is None:
                break
            i2, content = cur
            if i2 < ind:
                break
            if i2 > ind:
                raise YamlError("line %d: unexpected indent" % (self.i + 1))
            if _is_seq_item(content):
                break
            key, rest = _split_key(content)
            if key is None:
                raise YamlError("line %d: expected 'key: value', got %r"
                                % (self.i + 1, content))
            self.i += 1
            out[str(key)] = self._value(rest, ind)
        return out

    # -- sequences -------------------------------------------------------- #
    def _seq(self, ind: int) -> list:
        out: list = []
        while True:
            cur = self._cur()
            if cur is None:
                break
            i2, content = cur
            if i2 != ind or not _is_seq_item(content):
                if i2 > ind:
                    raise YamlError("line %d: unexpected indent" % (self.i + 1))
                break
            rest = content[1:].lstrip()
            if not rest:
                self.i += 1
                nxt = self._cur()
                if nxt is not None and nxt[0] > ind:
                    out.append(self._block(nxt[0]))
                else:
                    out.append(None)
                continue
            if _looks_like_mapping(rest):
                raw = self.lines[self.i]
                pad = ind + 2
                self.lines[self.i] = " " * pad + raw.lstrip(" ")[1:].lstrip()
                out.append(self._map(pad))
                continue
            self.i += 1
            out.append(self._inline_value(rest, ind))
        return out

    # -- values ----------------------------------------------------------- #
    def _value(self, rest: str, ind: int) -> Any:
        if not rest:
            nxt = self._cur()
            if nxt is None:
                return None
            if nxt[0] == ind and _is_seq_item(nxt[1]):
                return self._seq(ind)
            if nxt[0] <= ind:
                return None
            return self._block(nxt[0])
        return self._inline_value(rest, ind)

    def _inline_value(self, rest: str, ind: int) -> Any:
        if rest[0] in "|>":
            return self._block_scalar(rest, ind)
        if rest[0] in "\"'":
            return self._quoted(rest, ind)
        if rest[0] in "[{":
            return self._flow(rest, ind)
        if rest in ("~", "null", "Null", "NULL"):
            return None
        return _scalar(rest)

    def _block_scalar(self, header: str, ind: int) -> str:
        folded = header[0] == ">"
        chomp = header[1:].strip()
        collected: list[str] = []
        pending_blank = 0
        base = None
        while self.i < len(self.lines):
            raw = self.lines[self.i]
            if not raw.strip():
                pending_blank += 1
                self.i += 1
                continue
            ln = self._indent(raw)
            if ln <= ind:
                break
            if base is None:
                base = ln
            collected.extend([""] * pending_blank)
            pending_blank = 0
            collected.append(raw[base:] if ln >= base else raw.lstrip(" "))
            self.i += 1
        text = "\n".join(collected)
        if folded:
            parts = re.split(r"\n{2,}", text)
            text = "\n\n".join(" ".join(p.strip() for p in part.split("\n"))
                               for part in parts)
        if chomp.startswith("-"):
            pass
        elif chomp.startswith("+"):
            text = text + "\n"
        elif text:
            text = text + "\n"
        return text

    def _quoted(self, rest: str, ind: int) -> str:
        quote = rest[0]
        body = rest[1:]
        pieces: list[str] = []
        current = body
        while True:
            close = self._find_quote(current, quote)
            if close >= 0:
                pieces.append(current[:close])
                return _unescape("\n".join(pieces), quote)
            pieces.append(current)
            if self.i >= len(self.lines):
                raise YamlError("unterminated quoted scalar")
            nxt = self.lines[self.i]
            self.i += 1
            # continuation lines: drop the common indentation, keep the rest
            stripped = nxt.lstrip(" ")
            pad = len(nxt) - len(stripped)
            continuation_indent = min(pad, ind + 2)
            current = nxt[continuation_indent:] if len(nxt) >= continuation_indent else ""

    @staticmethod
    def _find_quote(text: str, quote: str) -> int:
        i = 0
        while i < len(text):
            c = text[i]
            if quote == '"' and c == "\\":
                i += 2
                continue
            if c == quote:
                if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                return i
            i += 1
        return -1

    def _flow(self, rest: str, ind: int) -> Any:
        text = rest
        while not self._balanced(text):
            if self.i >= len(self.lines):
                raise YamlError("unterminated flow collection")
            text += " " + self.lines[self.i].strip()
            self.i += 1
        return _Flow(text).parse()

    @staticmethod
    def _balanced(text: str) -> bool:
        depth = 0
        quote = None
        i = 0
        while i < len(text):
            c = text[i]
            if quote:
                if quote == '"' and c == "\\":
                    i += 2
                    continue
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c in "[{":
                depth += 1
            elif c in "]}":
                depth -= 1
            i += 1
        return depth <= 0 and quote is None


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def load(text: str) -> Any:
    """Parse a YAML document (the supported subset) into Python objects."""
    return _Parser(text).parse()


def load_file(path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return load(fh.read())
