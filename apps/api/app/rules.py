"""Safe cross-field rule expressions: a small tokenizer, parser and evaluator.

Rules such as ``subtotal + tax == total`` come from tenant configuration, so they
are parsed into a fixed grammar and evaluated by walking that tree. Nothing here
calls ``eval`` or ``exec``; unsupported syntax is rejected at configuration time.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

Value = Decimal | date | str | None
COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">="})
_TOKEN = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>==|!=|<=|>=|[-+*/()<>])"
)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    position: int


@dataclass(frozen=True)
class Number:
    value: Decimal


@dataclass(frozen=True)
class Name:
    name: str


@dataclass(frozen=True)
class Negate:
    operand: Expr


@dataclass(frozen=True)
class Arithmetic:
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Comparison:
    op: str
    left: Expr
    right: Expr


Expr = Number | Name | Negate | Arithmetic | Comparison


def tokenize(expression: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    while position < len(expression):
        if expression[position].isspace():
            position += 1
            continue
        match = _TOKEN.match(expression, position)
        if match is None or match.lastgroup is None:
            raise ValueError(f"Unexpected character {expression[position]!r} at {position}")
        text = match.group(match.lastgroup)
        if match.lastgroup == "name" and text.startswith("_"):
            raise ValueError(f"Identifier {text!r} may not start with an underscore")
        tokens.append(Token(match.lastgroup, text, position))
        position = match.end()
    tokens.append(Token("end", "", len(expression)))
    return tokens


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def take(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def accept(self, *ops: str) -> Token | None:
        if self.current.kind == "op" and self.current.text in ops:
            return self.take()
        return None

    def fail(self, message: str) -> ValueError:
        token = self.current
        shown = token.text or "end of expression"
        return ValueError(f"{message} near {shown!r} at {token.position}")

    def comparison(self) -> Expr:
        left = self.sum()
        operator = self.accept(*COMPARISONS)
        if operator is None:
            return left
        right = self.sum()
        if self.current.kind == "op" and self.current.text in COMPARISONS:
            raise self.fail("Chained comparisons are not supported")
        return Comparison(operator.text, left, right)

    def sum(self) -> Expr:
        left = self.term()
        while (operator := self.accept("+", "-")) is not None:
            left = Arithmetic(operator.text, left, self.term())
        return left

    def term(self) -> Expr:
        left = self.unary()
        while (operator := self.accept("*", "/")) is not None:
            left = Arithmetic(operator.text, left, self.unary())
        return left

    def unary(self) -> Expr:
        if self.accept("-") is not None:
            return Negate(self.unary())
        return self.primary()

    def primary(self) -> Expr:
        token = self.current
        if token.kind == "num":
            self.take()
            return Number(Decimal(token.text))
        if token.kind == "name":
            self.take()
            if self.current.kind == "op" and self.current.text == "(":
                raise self.fail("Function calls are not supported")
            return Name(token.text)
        if self.accept("(") is not None:
            inner = self.comparison()
            if self.accept(")") is None:
                raise self.fail("Expected ')'")
            return inner
        raise self.fail("Expected a number, field name or '('")


def parse(expression: str) -> Comparison:
    """Parse a rule; every rule must compare two values."""
    if not expression.strip():
        raise ValueError("Rule expression is empty")
    parser = _Parser(tokenize(expression))
    tree = parser.comparison()
    if parser.current.kind != "end":
        raise parser.fail("Unexpected token")
    if not isinstance(tree, Comparison):
        raise ValueError("Rule must compare two values, for example 'subtotal + tax == total'")
    return tree


def identifiers(expr: Expr) -> frozenset[str]:
    if isinstance(expr, Name):
        return frozenset({expr.name})
    if isinstance(expr, Negate):
        return identifiers(expr.operand)
    if isinstance(expr, Arithmetic | Comparison):
        return identifiers(expr.left) | identifiers(expr.right)
    return frozenset()


def _arithmetic(expr: Expr, values: Mapping[str, Value]) -> Value:
    if isinstance(expr, Number):
        return expr.value
    if isinstance(expr, Name):
        return values.get(expr.name)
    if isinstance(expr, Negate):
        operand = _arithmetic(expr.operand, values)
        return -operand if isinstance(operand, Decimal) else None
    if isinstance(expr, Comparison):
        return None
    left, right = _arithmetic(expr.left, values), _arithmetic(expr.right, values)
    if not isinstance(left, Decimal) or not isinstance(right, Decimal):
        return None
    try:
        if expr.op == "+":
            return left + right
        if expr.op == "-":
            return left - right
        if expr.op == "*":
            return left * right
        return left / right if right != 0 else None
    except InvalidOperation:
        return None


def evaluate(
    rule: Comparison, values: Mapping[str, Value], tolerance: Decimal = Decimal("0.01")
) -> bool | None:
    """Return True/False, or None when an operand is missing or not comparable."""
    left, right = _arithmetic(rule.left, values), _arithmetic(rule.right, values)
    if left is None or right is None:
        return None
    if isinstance(left, Decimal) and isinstance(right, Decimal):
        difference = left - right
        if rule.op == "==":
            return abs(difference) <= tolerance
        if rule.op == "!=":
            return abs(difference) > tolerance
        return _ordered(rule.op, difference, Decimal(0))
    if isinstance(left, date) and isinstance(right, date):
        if rule.op == "==":
            return left == right
        if rule.op == "!=":
            return left != right
        return _ordered(rule.op, left, right)
    if isinstance(left, str) and isinstance(right, str) and rule.op in {"==", "!="}:
        return (left == right) if rule.op == "==" else (left != right)
    return None


def _ordered(op: str, left: Decimal | date, right: Decimal | date) -> bool:
    # Both operands share a type here; mypy needs the branches spelled out.
    if isinstance(left, Decimal) and isinstance(right, Decimal):
        return _compare(op, left < right, left == right)
    if isinstance(left, date) and isinstance(right, date):
        return _compare(op, left < right, left == right)
    raise TypeError("Operands must share a type")


def _compare(op: str, less: bool, equal: bool) -> bool:
    if op == "<":
        return less
    if op == "<=":
        return less or equal
    if op == ">":
        return not less and not equal
    return not less
