"""Restricted expression language for `expr` in axes, `color`, `size` and filters (docs/api.md, Q1).

Grammar (case-insensitive keywords):

    expr    := or
    or      := and ("OR" and)*
    and     := not ("AND" not)*
    not     := "NOT" not | cmp
    cmp     := add [ ("<" | "<=" | ">" | ">=" | "=" | "!=" | "<>") add | "IS" ["NOT"] "NULL" ]
    add     := mul (("+" | "-") mul)*
    mul     := unary (("*" | "/") unary)*
    unary   := "-" unary | primary
    primary := number | 'string' | NULL | TRUE | FALSE | column | func "(" expr ("," expr)* ")"
             | "(" expr ")" | "CASE" ("WHEN" expr "THEN" expr)+ ["ELSE" expr] "END"

`column` is a bare identifier or a "double-quoted" one; `func` is one of ALLOWED_FUNCTIONS. Anything else (subqueries,
other functions, casts, `;`, `::`, comments) is a parse error. Validation is a real tokenizer + recursive-descent
parser, never a regex over the whole string.

`compile_expr` returns a normalised DuckDB SQL string built from the tokens (identifiers re-quoted, strings re-escaped),
so the SQL that runs is exactly what was parsed – never the raw input.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

ALLOWED_FUNCTIONS = frozenset(
    {"log", "log2", "log10", "ln", "abs", "sqrt", "round", "least", "greatest", "coalesce"}
)
KEYWORDS = frozenset({"and", "or", "not", "is", "null", "true", "false", "case", "when", "then", "else", "end"})
# bare words that would only make sense as SQL beyond the grammar; rejected with a clearer message
_SQL_WORDS = frozenset(
    {"select", "from", "where", "with", "union", "cast", "try_cast", "exists", "in", "like", "between", "over"}
)
MAX_LENGTH = 2000
MAX_DEPTH = 40

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<string>'(?:[^']|'')*')
  | (?P<qident>"(?:[^"]|"")+")
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|<>|!=|[<>=+\-*/(),])
    """,
    re.VERBOSE,
)


class ExprError(ValueError):
    """The expression is not allowed; the message says why (shown to the user and the LLM)."""


@dataclass
class Token:
    kind: str  # number | string | ident | qident | op | kw | eof
    text: str
    pos: int


def tokenize(expr: str) -> list[Token]:
    if not isinstance(expr, str) or not expr.strip():
        raise ExprError("expression is empty")
    if len(expr) > MAX_LENGTH:
        raise ExprError(f"expression is longer than {MAX_LENGTH} characters")
    out: list[Token] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            ch = expr[pos]
            hint = " (no statements, comments or casts)" if ch in ";:-[]{}" else ""
            raise ExprError(f"unexpected character {ch!r} at position {pos}{hint}")
        kind = m.lastgroup or ""
        text = m.group()
        if kind == "op" and text == "-" and expr.startswith("--", pos):
            raise ExprError(f"comments are not allowed (position {pos})")
        if kind == "op" and text == "/" and expr.startswith("/*", pos):
            raise ExprError(f"comments are not allowed (position {pos})")
        if kind != "ws":
            if kind == "ident" and text.lower() in KEYWORDS:
                kind = "kw"
                text = text.upper()
            out.append(Token(kind, text, pos))
        pos = m.end()
    out.append(Token("eof", "", len(expr)))
    return out


@dataclass
class CompiledExpr:
    sql: str
    columns: list[str] = field(default_factory=list)  # referenced columns (canonical names, first-seen order)


class _Parser:
    def __init__(self, tokens: list[Token], columns: dict[str, str] | None):
        self.toks = tokens
        self.i = 0
        self.depth = 0
        self.columns = columns  # lower-case name -> canonical name; None = accept any column
        self.used: dict[str, None] = {}
        self.unknown: dict[str, None] = {}

    # -- helpers
    @property
    def tok(self) -> Token:
        return self.toks[self.i]

    def _next(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def _is(self, kind: str, *texts: str) -> bool:
        t = self.tok
        return t.kind == kind and (not texts or t.text in texts)

    def _expect(self, kind: str, text: str) -> None:
        if not self._is(kind, text):
            raise ExprError(f"expected {text!r} at position {self.tok.pos}, got {self._describe(self.tok)}")
        self.i += 1

    @staticmethod
    def _describe(t: Token) -> str:
        return "end of expression" if t.kind == "eof" else repr(t.text)

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError("expression is nested too deeply")

    # -- grammar
    def parse(self) -> str:
        sql = self.or_()
        if self.tok.kind != "eof":
            raise ExprError(f"unexpected {self._describe(self.tok)} at position {self.tok.pos}")
        return sql

    def or_(self) -> str:
        self._enter()
        parts = [self.and_()]
        while self._is("kw", "OR"):
            self.i += 1
            parts.append(self.and_())
        self.depth -= 1
        return " OR ".join(parts)

    def and_(self) -> str:
        parts = [self.not_()]
        while self._is("kw", "AND"):
            self.i += 1
            parts.append(self.not_())
        return " AND ".join(parts)

    def not_(self) -> str:
        if self._is("kw", "NOT"):
            self.i += 1
            self._enter()
            inner = self.not_()
            self.depth -= 1
            return f"NOT {inner}"
        return self.cmp()

    def cmp(self) -> str:
        left = self.add()
        if self._is("op", "<", "<=", ">", ">=", "=", "!=", "<>"):
            op = self._next().text
            return f"{left} {op} {self.add()}"
        if self._is("kw", "IS"):
            self.i += 1
            neg = ""
            if self._is("kw", "NOT"):
                self.i += 1
                neg = "NOT "
            self._expect("kw", "NULL")
            return f"{left} IS {neg}NULL"
        return left

    def add(self) -> str:
        out = self.mul()
        while self._is("op", "+", "-"):
            op = self._next().text
            out = f"{out} {op} {self.mul()}"
        return out

    def mul(self) -> str:
        out = self.unary()
        while self._is("op", "*", "/"):
            op = self._next().text
            out = f"{out} {op} {self.unary()}"
        return out

    def unary(self) -> str:
        if self._is("op", "-"):
            self.i += 1
            self._enter()
            inner = self.unary()
            self.depth -= 1
            return f"-{inner}"
        return self.primary()

    def primary(self) -> str:
        t = self.tok
        if t.kind == "number":
            self.i += 1
            return t.text
        if t.kind == "string":
            self.i += 1
            value = t.text[1:-1].replace("''", "'")
            return "'" + value.replace("'", "''") + "'"
        if t.kind == "kw" and t.text in ("NULL", "TRUE", "FALSE"):
            self.i += 1
            return t.text
        if t.kind == "kw" and t.text == "CASE":
            return self.case()
        if t.kind == "op" and t.text == "(":
            self.i += 1
            self._enter()
            inner = self.or_()
            self.depth -= 1
            self._expect("op", ")")
            return f"({inner})"
        if t.kind == "ident" and self.toks[self.i + 1].kind == "op" and self.toks[self.i + 1].text == "(":
            return self.call()
        if t.kind == "ident" and t.text.lower() in _SQL_WORDS:
            raise ExprError(f"{t.text!r} is not allowed: no subqueries, casts or SQL statements in expressions")
        if t.kind in ("ident", "qident"):
            self.i += 1
            name = t.text if t.kind == "ident" else t.text[1:-1].replace('""', '"')
            return self.column(name)
        raise ExprError(f"unexpected {self._describe(t)} at position {t.pos}")

    def call(self) -> str:
        t = self._next()
        name = t.text.lower()
        if name not in ALLOWED_FUNCTIONS:
            raise ExprError(
                f"function {t.text!r} is not allowed (allowed: {', '.join(sorted(ALLOWED_FUNCTIONS))})"
            )
        self._expect("op", "(")
        if self._is("op", ")"):
            raise ExprError(f"function {name}() needs at least one argument")
        self._enter()
        args = [self.or_()]
        while self._is("op", ","):
            self.i += 1
            args.append(self.or_())
        self.depth -= 1
        self._expect("op", ")")
        return f"{name}({', '.join(args)})"

    def case(self) -> str:
        self._expect("kw", "CASE")
        self._enter()
        parts = ["CASE"]
        if not self._is("kw", "WHEN"):
            raise ExprError(f"expected 'WHEN' after CASE at position {self.tok.pos} (only CASE WHEN ... is allowed)")
        while self._is("kw", "WHEN"):
            self.i += 1
            cond = self.or_()
            self._expect("kw", "THEN")
            parts.append(f"WHEN {cond} THEN {self.or_()}")
        if self._is("kw", "ELSE"):
            self.i += 1
            parts.append(f"ELSE {self.or_()}")
        self._expect("kw", "END")
        self.depth -= 1
        parts.append("END")
        return " ".join(parts)

    def column(self, name: str) -> str:
        if self.columns is not None:
            canonical = self.columns.get(name.lower())
            if canonical is None:
                self.unknown[name] = None
                canonical = name
        else:
            canonical = name
        self.used[canonical] = None
        return '"' + canonical.replace('"', '""') + '"'


def compile_expr(expr: str, columns: Iterable[str] | None = None) -> CompiledExpr:
    """Parse `expr`; return normalised SQL and the referenced columns. Raises ExprError.

    With `columns`, every referenced column must be one of them (matched case-insensitively, like DuckDB, and
    rewritten to the canonical spelling).
    """
    colmap = None if columns is None else {c.lower(): c for c in columns}
    parser = _Parser(tokenize(expr), colmap)
    sql = parser.parse()
    if parser.unknown:
        names = ", ".join(repr(n) for n in parser.unknown)
        raise ExprError(f"unknown column {names}")
    return CompiledExpr(sql=sql, columns=list(parser.used))
