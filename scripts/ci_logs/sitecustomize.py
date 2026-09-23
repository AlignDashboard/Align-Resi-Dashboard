"""Redact figures from everything Python prints inside GitHub Actions.

The repository is public, so its Actions logs are public too -- and the pipeline
prints the very figures the data files are sealed to protect: every filled KPI
(a line like "Budget Variance % +$NNN,NNN/+NN.N%"), comp-implied rents, revenue
per month, tie-out amounts inside parser errors. Sealing the files while printing their
contents to a public log would leave the job half done.

Rather than touching dozens of print statements (and every future one), this
module rewrites stdout and stderr for the whole interpreter. The workflows put
this directory on PYTHONPATH, so it applies to every python process a job starts,
subprocesses and tracebacks included. It does nothing outside Actions, so local
runs print everything as before; set ALIGN_LOG_REDACT=0 to switch it off in CI.

What is masked: currency, percentages, comma-grouped numbers, any decimal, and
bare integers of four or more digits (signed or not) other than years. What is
kept: dates, times, years, filenames, counts under a thousand, workflow commands
(::error:: etc.). A count of leases is not the problem; a rent is.
"""
import os
import re
import sys

PATTERNS = [
    # currency, with or without a sign, grouping, decimals or a k/M suffix
    (re.compile(r"[-+\u2212]?\$\s?[-\u2212]?\d[\d,]*(?:\.\d+)?(?:\s?[kKmMbB](?![a-zA-Z]))?"), "$\u2039\u2026\u203a"),
    # percentages
    (re.compile(r"[-+\u2212]?\d+(?:\.\d+)?\s?%"), "\u2039\u2026\u203a%"),
    # comma-grouped numbers
    (re.compile(r"(?<![\w.])[-\u2212]?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)"), "\u2039n\u203a"),
    # any decimal -- one place is enough: inspect's ratios print as "Aug=32.6"
    (re.compile(r"(?<![\w.:])[-\u2212]?\d+\.\d+(?!\d)"), "\u2039n\u203a"),
    # bare integers of four or more digits, signed or not -- except years
    (re.compile(r"(?<![\w.:])[-\u2212]?(?!(?:19|20)\d\d(?!\d))\d{4,}(?![\w-])"), "\u2039n\u203a"),
]


def redact(text):
    for pat, repl in PATTERNS:
        text = pat.sub(repl, text)
    return text


class _Redacting:
    """A text stream that redacts whole lines, so a figure split across two
    write() calls (print with several arguments) is still caught."""

    def __init__(self, stream):
        self._s = stream
        self._buf = ""

    def write(self, text):
        self._buf += text
        if "\n" in self._buf:
            head, self._buf = self._buf.rsplit("\n", 1)
            self._s.write(redact(head) + "\n")
        return len(text)

    def flush(self):
        if self._buf:
            self._s.write(redact(self._buf))
            self._buf = ""
        self._s.flush()

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):              # encoding, isatty, buffer, fileno ...
        return getattr(self._s, name)


if os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("ALIGN_LOG_REDACT") != "0":
    sys.stdout = _Redacting(sys.stdout)
    sys.stderr = _Redacting(sys.stderr)
