"""One-shot extractor: parse the static dashboard's ``apts`` JS array into JSON.

The canonical static dashboard lives at
``Static Dashboard References/alewife_dashboard_v2.html``. It embeds a
hand-curated list of apartment buildings inside a JS literal that starts
at ``const apts = [`` and ends at the matching closing bracket. This
script reads that block, converts the JS object syntax to JSON, and
writes ``app/seed/buildings_seed.json``.

The script is intentionally forgiving: it handles trailing commas, single
quotes, unquoted object keys, ``null`` tokens, and inline JS comments.

Usage::

    python -m scripts.extract_seed \
        --source "../../Static Dashboard References/alewife_dashboard_v2.html" \
        --output app/seed/buildings_seed.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent.parent
DEFAULT_SOURCE = REPO_ROOT / "Static Dashboard References" / "alewife_dashboard_v2.html"
DEFAULT_OUTPUT = BACKEND_DIR / "app" / "seed" / "buildings_seed.json"

APTS_BLOCK_START = "const apts = ["


def _slugify(name: str) -> str:
    """Turn a building name into a URL-friendly slug.

    Lowercases, strips non-alphanumerics, collapses whitespace and
    hyphens. Stable across runs so re-seeding is idempotent.
    """

    lowered = name.lower().strip()
    replaced = re.sub(r"[^a-z0-9]+", "-", lowered)
    return replaced.strip("-")


def _extract_apts_literal(html: str) -> str:
    """Return the JS array literal starting at ``const apts = [``.

    Walks the source after the marker and tracks bracket depth, respecting
    quoted strings so brackets inside descriptions don't confuse us.
    """

    start = html.find(APTS_BLOCK_START)
    if start == -1:
        raise ValueError(f"Marker {APTS_BLOCK_START!r} not found in source file")

    array_start = html.index("[", start)
    depth = 0
    in_string: str | None = None
    escape = False

    for index in range(array_start, len(html)):
        char = html[index]

        if in_string is not None:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            continue

        if char in ('"', "'"):
            in_string = char
            continue

        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return html[array_start : index + 1]

    raise ValueError("Unterminated array literal while extracting apts block")


_IDENT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")


def _js_to_json(js_literal: str) -> str:
    """Normalize a forgiving JS array literal into strict JSON.

    Uses a single-pass tokenizer that tracks string context so that:

    - ``//`` and ``/* */`` comments are stripped only outside strings
    - unquoted object keys (``name:``) get double-quoted
    - single-quoted strings are rewritten as double-quoted JSON strings
    - trailing commas before ``]`` / ``}`` are removed

    The dashboard's JS dialect is simple enough for this targeted
    rewriter; we do not attempt to be a general JS parser.
    """

    result: list[str] = []
    index = 0
    length = len(js_literal)

    while index < length:
        char = js_literal[index]

        if char == '"' or char == "'":
            literal, consumed = _read_js_string(js_literal, index)
            result.append(literal)
            index += consumed
            continue

        if char == "/" and index + 1 < length:
            next_char = js_literal[index + 1]
            if next_char == "/":
                newline = js_literal.find("\n", index + 2)
                index = length if newline == -1 else newline
                continue
            if next_char == "*":
                end = js_literal.find("*/", index + 2)
                index = length if end == -1 else end + 2
                continue

        if char in _IDENT_START:
            ident_end = index
            while ident_end < length and js_literal[ident_end] in _IDENT_CHARS:
                ident_end += 1
            identifier = js_literal[index:ident_end]
            lookahead = ident_end
            while lookahead < length and js_literal[lookahead] in (" ", "\t"):
                lookahead += 1
            is_object_key = lookahead < length and js_literal[lookahead] == ":"
            if is_object_key and identifier not in {"true", "false", "null"}:
                result.append(f'"{identifier}"')
            else:
                result.append(identifier)
            index = ident_end
            continue

        result.append(char)
        index += 1

    stitched = "".join(result)
    return re.sub(r",(\s*[\]}])", r"\1", stitched)


def _read_js_string(source: str, start: int) -> tuple[str, int]:
    """Read a JS string literal and return ``(json_literal, consumed_chars)``.

    Normalizes single-quoted strings into JSON double-quoted form.
    """

    quote = source[start]
    index = start + 1
    buffer: list[str] = []
    escape = False
    length = len(source)

    while index < length:
        char = source[index]
        if escape:
            buffer.append(char)
            escape = False
            index += 1
            continue
        if char == "\\":
            buffer.append(char)
            escape = True
            index += 1
            continue
        if char == quote:
            return json.dumps("".join(buffer)), index - start + 1
        buffer.append(char)
        index += 1

    raise ValueError(f"Unterminated string literal starting at offset {start}")


def parse_apts(html: str) -> list[dict[str, object]]:
    """Return the list of apartment dicts parsed from the dashboard HTML."""

    literal = _extract_apts_literal(html)
    json_ready = _js_to_json(literal)
    parsed = json.loads(json_ready)
    if not isinstance(parsed, list):
        raise ValueError("Parsed apts block is not a JSON array")
    return parsed


def enrich_with_slug(buildings: list[dict[str, object]]) -> list[dict[str, object]]:
    """Attach a stable ``slug`` to each building record."""

    enriched: list[dict[str, object]] = []
    seen: set[str] = set()
    for building in buildings:
        name = building.get("name")
        if not isinstance(name, str):
            raise ValueError(f"Building entry missing string 'name': {building!r}")
        slug = _slugify(name)
        if slug in seen:
            raise ValueError(f"Duplicate slug generated: {slug!r}")
        seen.add(slug)
        enriched.append({"slug": slug, **building})
    return enriched


def extract(source: Path, output: Path) -> int:
    """Read ``source``, parse the apts block, and write ``output``.

    Returns the number of buildings written.
    """

    html = source.read_text(encoding="utf-8")
    buildings = enrich_with_slug(parse_apts(html))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(buildings, indent=2) + "\n", encoding="utf-8")
    return len(buildings)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> None:
    """Entry point for ``python -m scripts.extract_seed``."""

    args = _build_arg_parser().parse_args()
    count = extract(args.source, args.output)
    print(f"Wrote {count} buildings to {args.output}")


if __name__ == "__main__":
    main()
