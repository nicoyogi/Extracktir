"""Template-driven field extraction.

A *template* is a small YAML or JSON document that describes the fields you
want to pull from a specific kind of PDF (an invoice format, a bank
statement layout, a tax form). When a template is supplied, Extracktir
applies its rules **in addition to** the generic key-value heuristic, so
you get both: deterministic named fields, plus anything else the heuristic
catches.

A template looks like this::

    name: acme-invoice
    description: ACME Corp invoices, 2026 layout

    # Optional: only apply this template if all `match` patterns appear
    # somewhere in the document text.
    match:
      - "ACME Corp"
      - "Invoice"

    fields:
      - name: invoice_number
        type: regex
        pattern: "Invoice Number:\\s*(?P<value>\\S+)"

      - name: total
        type: regex
        pattern: "Total Amount:\\s*\\$?(?P<value>[\\d,.]+)"
        cast: number

      - name: bill_to
        type: after_label
        label: "Bill To"

      - name: due_date
        type: after_label
        label: "Due Date"
        cast: date

Field rule types
----------------

* ``regex`` — a Python regex applied to the full document text. The value
  is taken from the named group ``value`` if present, otherwise group 1,
  otherwise the whole match.
* ``after_label`` — find the line containing ``label`` and take whatever
  follows it (after ``:`` or 2+ spaces). If the label line has nothing
  after it, the next non-empty line is used.

Optional ``cast`` values: ``number``, ``date``, ``string`` (default).

JSON templates use the same schema with JSON syntax.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:  # PyYAML is in requirements but keep this import resilient
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


# -- Casting ----------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_DATE_RES = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),
    re.compile(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b"),
    re.compile(r"\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b"),
]


def _cast(value: str, cast: str | None) -> Any:
    if not value:
        return value
    v = value.strip()
    if not cast or cast == "string":
        return v
    if cast == "number":
        m = _NUMBER_RE.search(v)
        if not m:
            return v
        try:
            cleaned = m.group(0).replace(",", "")
            return float(cleaned) if "." in cleaned else int(cleaned)
        except ValueError:
            return v
    if cast == "date":
        for pat in _DATE_RES:
            m = pat.search(v)
            if m:
                return m.group(0)
        return v
    return v


# -- Schema -----------------------------------------------------------------


@dataclass
class FieldRule:
    name: str
    type: str  # "regex" | "after_label"
    pattern: str | None = None
    label: str | None = None
    cast: str | None = None
    flags: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FieldRule":
        if "name" not in d:
            raise ValueError("template field missing 'name'")
        t = d.get("type", "regex")
        if t not in {"regex", "after_label"}:
            raise ValueError(
                f"field {d['name']!r}: unknown type {t!r} "
                "(expected 'regex' or 'after_label')"
            )
        if t == "regex" and not d.get("pattern"):
            raise ValueError(f"field {d['name']!r}: regex rule needs 'pattern'")
        if t == "after_label" and not d.get("label"):
            raise ValueError(f"field {d['name']!r}: after_label rule needs 'label'")

        flags = 0
        flag_str = d.get("flags", "")
        if isinstance(flag_str, str):
            for ch in flag_str.upper():
                flags |= {"I": re.IGNORECASE, "M": re.MULTILINE, "S": re.DOTALL}.get(ch, 0)
        return cls(
            name=str(d["name"]),
            type=t,
            pattern=d.get("pattern"),
            label=d.get("label"),
            cast=d.get("cast"),
            flags=flags,
        )


@dataclass
class Template:
    name: str
    description: str = ""
    match: list[str] = field(default_factory=list)
    fields: list[FieldRule] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Template":
        if "fields" not in d or not isinstance(d["fields"], list):
            raise ValueError("template missing 'fields' list")
        return cls(
            name=str(d.get("name", "template")),
            description=str(d.get("description", "")),
            match=[str(x) for x in (d.get("match") or [])],
            fields=[FieldRule.from_dict(f) for f in d["fields"]],
        )

    @classmethod
    def from_text(cls, text: str, *, fmt: str = "auto") -> "Template":
        text = text.strip()
        if not text:
            raise ValueError("empty template")
        if fmt == "auto":
            fmt = "json" if text.lstrip().startswith("{") else "yaml"
        if fmt == "json":
            data = json.loads(text)
        elif fmt == "yaml":
            if yaml is None:
                raise RuntimeError("PyYAML is required to load YAML templates")
            data = yaml.safe_load(text)
        else:
            raise ValueError(f"unknown template format {fmt!r}")
        if not isinstance(data, dict):
            raise ValueError("template root must be a mapping/object")
        return cls.from_dict(data)

    @classmethod
    def from_path(cls, path: str | Path) -> "Template":
        p = Path(path)
        fmt = "json" if p.suffix.lower() == ".json" else "yaml"
        return cls.from_text(p.read_text(encoding="utf-8"), fmt=fmt)

    # -- application --------------------------------------------------------

    def matches(self, full_text: str) -> bool:
        """Return True if all ``match`` substrings appear in ``full_text``.

        An empty ``match`` list always matches.
        """
        return all(needle in full_text for needle in self.match)

    def apply(self, page_texts: Iterable[str]) -> list[dict[str, Any]]:
        """Apply this template across the document and return one row per
        configured field. Missing fields are returned with ``Value=None`` so
        the caller can see the schema.
        """
        pages = list(page_texts)
        full_text = "\n".join(pages)
        out: list[dict[str, Any]] = []
        for rule in self.fields:
            value, page = self._apply_rule(rule, pages, full_text)
            out.append(
                {
                    "Field": rule.name,
                    "Value": _cast(value, rule.cast) if value is not None else None,
                    "Page": page,
                    "Source": "template",
                }
            )
        return out

    def _apply_rule(
        self, rule: FieldRule, pages: list[str], full_text: str
    ) -> tuple[str | None, int | None]:
        if rule.type == "regex":
            assert rule.pattern is not None
            pat = re.compile(rule.pattern, rule.flags)
            # Search per-page first so we can attribute a page number.
            for i, text in enumerate(pages, start=1):
                m = pat.search(text)
                if m:
                    return self._extract_match(m), i
            m = pat.search(full_text)
            return (self._extract_match(m), None) if m else (None, None)

        if rule.type == "after_label":
            assert rule.label is not None
            return self._after_label(rule.label, pages)

        return None, None

    @staticmethod
    def _extract_match(m: re.Match[str]) -> str:
        if "value" in m.groupdict():
            return (m.group("value") or "").strip()
        if m.groups():
            return (m.group(1) or "").strip()
        return m.group(0).strip()

    @staticmethod
    def _after_label(label: str, pages: list[str]) -> tuple[str | None, int | None]:
        # Match "Label: value" or "Label   value" (2+ spaces), case-insensitive.
        inline = re.compile(
            rf"(?im)^\s*{re.escape(label)}\s*[:\-]?\s+(?P<v>\S.*?)\s*$"
        )
        bare = re.compile(rf"(?im)^\s*{re.escape(label)}\s*[:\-]?\s*$")
        for i, text in enumerate(pages, start=1):
            for line_match in inline.finditer(text):
                value = line_match.group("v").strip()
                if value:
                    return value, i
            for bm in bare.finditer(text):
                # Take next non-empty line.
                tail = text[bm.end():].splitlines()
                for ln in tail:
                    if ln.strip():
                        return ln.strip(), i
        return None, None


def load_template(source: str | Path | dict[str, Any] | None) -> Template | None:
    """Convenience loader.

    * ``None`` -> ``None``
    * ``dict`` -> ``Template.from_dict``
    * path-like ending in .json/.yaml/.yml -> read from disk
    * other strings -> treated as inline YAML/JSON text
    """
    if source is None:
        return None
    if isinstance(source, Template):
        return source
    if isinstance(source, dict):
        return Template.from_dict(source)
    if isinstance(source, Path):
        return Template.from_path(source)
    if isinstance(source, str):
        # Distinguish path vs. inline text. A path-shaped string that
        # has a templating extension is always treated as a path so that
        # missing-file errors surface, even if it doesn't exist on disk.
        looks_like_path = (
            "\n" not in source
            and len(source) < 1024
            and (
                Path(source).exists()
                or Path(source).suffix.lower() in {".yaml", ".yml", ".json"}
            )
        )
        if looks_like_path:
            return Template.from_path(source)
        return Template.from_text(source)
    raise TypeError(f"unsupported template source: {type(source).__name__}")
