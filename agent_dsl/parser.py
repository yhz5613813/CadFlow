"""Safe parser for the CadFlow agent DSL.

The grammar deliberately has no expression evaluation, imports, attribute
access, or arbitrary Python.  Values are parsed as finite numbers, names, and
bounded vectors only.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
import shlex
from typing import Any


class DSLParseError(ValueError):
    """Raised when a DSL document does not match the supported grammar."""


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_TAG = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
MAX_INSPECTION_ITEMS = 64


@dataclass(frozen=True)
class Instruction:
    """One validated instruction and its source location."""

    op: str
    args: tuple[Any, ...]
    line: int
    source: str


def _error(line: int, source: str, message: str) -> DSLParseError:
    return DSLParseError(f"line {line}: {message}: {source.strip()!r}")


def _name(value: str, line: int, source: str) -> str:
    if not _NAME.fullmatch(value):
        raise _error(line, source, f"invalid name {value!r}")
    return value


def _tag(value: str, line: int, source: str) -> str:
    if not _TAG.fullmatch(value):
        raise _error(line, source, f"invalid tag {value!r}")
    return value.lower()


def _number(value: str, line: int, source: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise _error(line, source, f"expected a number, got {value!r}") from exc
    if not math.isfinite(result):
        raise _error(line, source, "numbers must be finite")
    return result


def _integer(value: str, line: int, source: str) -> int:
    number = _number(value, line, source)
    if number != int(number):
        raise _error(line, source, f"expected an integer, got {value!r}")
    return int(number)


def _vector(tokens: list[str], start: int, line: int, source: str) -> tuple[tuple[float, float, float], int]:
    if start + 3 > len(tokens):
        raise _error(line, source, "expected three vector values")
    return (
        (
            _number(tokens[start], line, source),
            _number(tokens[start + 1], line, source),
            _number(tokens[start + 2], line, source),
        ),
        start + 3,
    )


def _selection(value: str, line: int, source: str) -> tuple[str, Any]:
    if value.lower().startswith("tag:"):
        return "tag", _tag(value[4:], line, source)
    values = tuple(part for part in value.split(",") if part)
    if not values:
        raise _error(line, source, "edge/face selection cannot be empty")
    result = tuple(_integer(part, line, source) for part in values)
    if any(item < 0 for item in result) or len(set(result)) != len(result):
        raise _error(line, source, "selections must be unique non-negative indices")
    return "indices", result


def _keyword_options(
    tokens: list[str],
    index: int,
    line: int,
    source: str,
    *,
    allowed: set[str],
) -> dict[str, Any]:
    options: dict[str, Any] = {}
    while index < len(tokens):
        keyword = tokens[index].lower()
        index += 1
        if keyword not in allowed:
            raise _error(line, source, f"unknown option {tokens[index - 1]!r}")
        if keyword in options:
            raise _error(line, source, f"duplicate option {tokens[index - 1]!r}")
        if keyword in {"at", "axis", "origin", "normal"}:
            value, index = _vector(tokens, index, line, source)
            options[keyword] = value
        elif keyword in {"top_radius", "tolerance", "limit", "solid", "ruled", "frenet"}:
            if index >= len(tokens):
                raise _error(line, source, f"missing value for {keyword}")
            raw = tokens[index]
            index += 1
            if keyword in {"solid", "ruled", "frenet"}:
                if raw.lower() not in {"true", "false", "1", "0"}:
                    raise _error(line, source, f"{keyword} must be true or false")
                options[keyword] = raw.lower() in {"true", "1"}
            elif keyword == "limit":
                options[keyword] = _integer(raw, line, source)
            else:
                options[keyword] = _number(raw, line, source)
        elif keyword in {"edges", "faces"}:
            if index >= len(tokens):
                raise _error(line, source, f"missing selection for {keyword}")
            options[keyword] = _selection(tokens[index], line, source)
            index += 1
        else:
            raise _error(line, source, f"unknown option {tokens[index - 1]!r}")
    return options


def _split_equals(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        if "=" in token and not token.startswith("="):
            key, value = token.split("=", 1)
            if key and value:
                expanded.extend((key, value))
                continue
        expanded.append(token)
    return expanded


def _parse_line(tokens: list[str], line: int, source: str) -> Instruction:
    if not tokens:
        raise _error(line, source, "empty instruction")
    op = tokens[0].lower()
    if op in {"checkpoint", "rollback"}:
        if len(tokens) != 2:
            raise _error(line, source, f"{op} requires one label")
        return Instruction(op, (_name(tokens[1], line, source),), line, source)
    if op == "result":
        if len(tokens) != 2:
            raise _error(line, source, "result requires one shape name")
        return Instruction(op, (_name(tokens[1], line, source),), line, source)
    if op == "tag":
        if len(tokens) != 3:
            raise _error(line, source, "tag requires a shape name and tag")
        return Instruction(op, (_name(tokens[1], line, source), _tag(tokens[2], line, source)), line, source)
    if op == "inspect":
        if len(tokens) < 2:
            raise _error(line, source, "inspect requires a shape name")
        name = _name(tokens[1], line, source)
        field_names = {
            "kind", "volume", "area", "surface_area", "bbox", "topology",
            "tags", "center_of_mass", "faces", "edges",
        }
        field_tokens: list[str] = []
        option_start = len(tokens)
        for index, token in enumerate(tokens[2:], 2):
            if token.lower() == "limit" or token.lower().startswith("limit="):
                option_start = index
                break
            if token.lower() not in field_names:
                raise _error(line, source, f"unknown inspect field {token!r}")
            field_tokens.append(token.lower())
        fields = tuple(field_tokens)
        options = (
            _keyword_options(
                tokens, option_start, line, source, allowed={"limit"}
            )
            if option_start < len(tokens)
            else {}
        )
        if "limit" in options and not 1 <= options["limit"] <= MAX_INSPECTION_ITEMS:
            raise _error(
                line,
                source,
                f"inspect limit must be between 1 and {MAX_INSPECTION_ITEMS}",
            )
        return Instruction(op, (name, fields, options.get("limit", 12)), line, source)
    if op == "export":
        if len(tokens) != 4 or tokens[2].lower() != "step":
            raise _error(line, source, "export syntax is: export SHAPE step PATH")
        return Instruction(op, (_name(tokens[1], line, source), "step", tokens[3]), line, source)
    if op == "preview":
        if len(tokens) not in {2, 3}:
            raise _error(
                line,
                source,
                "preview syntax is: preview SHAPE [draft|final]",
            )
        quality = tokens[2].lower() if len(tokens) == 3 else "draft"
        if quality not in {"draft", "final"}:
            raise _error(line, source, "preview quality must be draft or final")
        return Instruction(
            op,
            (_name(tokens[1], line, source), quality),
            line,
            source,
        )

    constructors = {"box", "cylinder", "cone", "sphere"}
    if op in constructors:
        if len(tokens) < 3:
            raise _error(line, source, f"{op} has too few arguments")
        name = _name(tokens[1], line, source)
        if op == "box":
            if len(tokens) < 5:
                raise _error(line, source, "box requires width height depth")
            args: tuple[Any, ...] = (name, _number(tokens[2], line, source), _number(tokens[3], line, source), _number(tokens[4], line, source))
            options = (
                _keyword_options(tokens, 5, line, source, allowed={"at"})
                if len(tokens) > 5
                else {}
            )
            return Instruction(op, args + (options,), line, source)
        if op == "cylinder":
            if len(tokens) < 4:
                raise _error(line, source, "cylinder requires radius height")
            args = (name, _number(tokens[2], line, source), _number(tokens[3], line, source))
            options = (
                _keyword_options(
                    tokens, 4, line, source, allowed={"at", "axis"}
                )
                if len(tokens) > 4
                else {}
            )
            return Instruction(op, args + (options,), line, source)
        if op == "cone":
            if len(tokens) < 4:
                raise _error(line, source, "cone requires bottom_radius height")
            args = (name, _number(tokens[2], line, source), _number(tokens[3], line, source))
            options = (
                _keyword_options(
                    tokens,
                    4,
                    line,
                    source,
                    allowed={"at", "axis", "top_radius"},
                )
                if len(tokens) > 4
                else {}
            )
            return Instruction(op, args + (options,), line, source)
        args = (name, _number(tokens[2], line, source))
        options = (
            _keyword_options(tokens, 3, line, source, allowed={"at"})
            if len(tokens) > 3
            else {}
        )
        return Instruction(op, args + (options,), line, source)

    if op in {"cut", "union", "intersect"}:
        if len(tokens) < 4:
            raise _error(line, source, f"{op} requires an output and at least two inputs")
        return Instruction(op, (_name(tokens[1], line, source), tuple(_name(token, line, source) for token in tokens[2:])), line, source)

    if op in {"translate", "rotate", "mirror", "fillet", "chamfer", "shell"}:
        if len(tokens) < 3:
            raise _error(line, source, f"{op} has too few arguments")
        output, source_name = _name(tokens[1], line, source), _name(tokens[2], line, source)
        if op == "translate":
            if len(tokens) != 6:
                raise _error(line, source, "translate syntax is: translate OUT IN dx dy dz")
            values = tuple(_number(item, line, source) for item in tokens[3:6])
            return Instruction(op, (output, source_name, values), line, source)
        if op in {"fillet", "chamfer", "shell"}:
            if len(tokens) < 5:
                raise _error(line, source, f"{op} requires a size and selection")
            size = _number(tokens[3], line, source)
            expected = "faces" if op == "shell" else "edges"
            options = _keyword_options(
                tokens, 4, line, source, allowed={expected}
            )
            if expected not in options:
                raise _error(line, source, f"{op} requires {expected} N[,N]")
            return Instruction(op, (output, source_name, size, options), line, source)
        if op == "rotate":
            if len(tokens) < 4:
                raise _error(line, source, "rotate requires degrees")
            degrees = _number(tokens[3], line, source)
            options = (
                _keyword_options(
                    tokens, 4, line, source, allowed={"axis", "origin"}
                )
                if len(tokens) > 4
                else {}
            )
            return Instruction(op, (output, source_name, degrees, options), line, source)
        if op == "mirror":
            options = _keyword_options(
                tokens, 3, line, source, allowed={"normal", "origin"}
            )
            if "normal" not in options:
                raise _error(
                    line,
                    source,
                    "mirror requires normal nx ny nz and accepts origin ox oy oz",
                )
            return Instruction(op, (output, source_name, options), line, source)
    raise _error(line, source, f"unknown operation {tokens[0]!r}")


def parse(document: str) -> tuple[Instruction, ...]:
    """Parse a DSL document into immutable validated instructions."""
    if not isinstance(document, str):
        raise TypeError("DSL document must be a string")
    instructions: list[Instruction] = []
    for line_number, raw_line in enumerate(document.splitlines(), 1):
        source = raw_line.strip()
        if not source or source.startswith("#"):
            continue
        try:
            tokens = _split_equals(shlex.split(raw_line, comments=True, posix=True))
        except ValueError as exc:
            raise _error(line_number, raw_line, str(exc)) from exc
        if tokens:
            instructions.append(_parse_line(tokens, line_number, raw_line))
    if not instructions:
        raise DSLParseError("DSL document contains no instructions")
    return tuple(instructions)
