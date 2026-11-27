"""Console hardening shared by the operator scripts.

``print`` raises ``UnicodeEncodeError`` when the terminal code page cannot encode the text.  The
probe helpers decode subprocess output with ``errors="replace"``, so one stray byte becomes
U+FFFD, which the GBK console cannot encode: ``preflight.py`` crashed on exactly that before it
could report anything (measured on a Chinese Windows terminal).  The same applies to printed
paths and agent-supplied Chinese titles in ``review.py``/``agent_facts.py``.

Keep the console encoding as it is -- replacing the *unencodable* characters keeps CJK text
readable where the terminal supports it, while a forced UTF-8 would print mojibake on a GBK
console.
"""

from __future__ import annotations

import sys


def harden_stdout() -> None:
    """Make ``print`` survive characters the console code page cannot encode."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # e.g. a redirected StringIO in tests
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):  # a closed or detached stream must not break the run
            continue
