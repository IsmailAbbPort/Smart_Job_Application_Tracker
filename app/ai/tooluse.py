"""Coerce a model's tool-use output into something its schema will accept.

Tool-use forces Claude to return JSON matching an input_schema, but smaller/faster
models (Haiku especially) still bend it under load. The failure we actually see on
the judge is reproducible: two adjacent list fields (`matched_requirements` then
`gaps`) come back collapsed into ONE string field, their JSON arrays concatenated,
and the second field's key dropped entirely. `model_validate` then 500s on an
otherwise usable verdict.

This normalizes the raw tool input before validation:

1. Any structured field (list/dict/model) that arrived as a JSON *string* is parsed.
   `raw_decode` is used, so a string holding several concatenated JSON values yields
   the first value for that field and keeps the rest as overflow.
2. Any required list field the model dropped is backfilled - first from that overflow
   (recovering a field the model merged into its neighbour), else an empty list.

It is schema-aware (only touches fields the target declares as list/dict/model), so
natural-language strings like "[NEEDS INPUT: ...]" are left alone. Shared by the
judge and the cover-letter fabrication check.
"""

from __future__ import annotations

import json
from typing import get_origin

from pydantic import BaseModel

# strict=False tolerates raw control chars (literal newlines/tabs) inside string
# values, which the model routinely leaves in cv_evidence/requirement text and which
# a strict parser rejects as "Invalid control character".
_DECODER = json.JSONDecoder(strict=False)


def _is_structured(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin in (list, dict, tuple):
        return True
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _salvage_array(text: str, start: int) -> list:
    """Recover the complete leading elements of an array that was cut off mid-value
    (the model exceeded max_tokens). `text[start]` is '['; the tail is discarded."""
    items: list = []
    idx, n = start + 1, len(text)
    while idx < n:
        while idx < n and text[idx] in " \t\r\n,":
            idx += 1
        if idx >= n or text[idx] == "]":
            break
        try:
            value, idx = _DECODER.raw_decode(text, idx)
        except ValueError:
            break  # truncated element - stop with what parsed cleanly
        items.append(value)
    return items


def _decode_json_values(text: str) -> list:
    """Every top-level JSON value in `text`, in order. One clean array -> one value;
    two concatenated arrays -> two. A trailing array truncated mid-element is salvaged
    down to its complete elements rather than lost."""
    values: list = []
    idx, n = 0, len(text)
    while idx < n:
        while idx < n and text[idx].isspace():
            idx += 1
        if idx >= n:
            break
        try:
            value, idx = _DECODER.raw_decode(text, idx)
        except ValueError:
            if text[idx] == "[":
                values.append(_salvage_array(text, idx))
            break
        values.append(value)
    return values


def coerce_tool_input(model_cls: type[BaseModel], raw: dict) -> dict:
    """Return a copy of `raw` massaged to fit `model_cls`'s schema (see module docstring)."""
    data = dict(raw)
    overflow: list = []  # extra JSON values pulled out of a stringified field
    for name, field in model_cls.model_fields.items():
        if name in data and isinstance(data[name], str) and _is_structured(field.annotation):
            decoded = _decode_json_values(data[name])
            if decoded:
                data[name] = decoded[0]
                overflow.extend(decoded[1:])
    # Backfill list fields the model dropped: from overflow when it merged one field
    # into another's string, otherwise empty so a partial verdict degrades, not 500s.
    for name, field in model_cls.model_fields.items():
        if get_origin(field.annotation) is list and data.get(name) is None and field.is_required():
            data[name] = overflow.pop(0) if overflow else []
    return data
