from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scorepipe.console import harden_stdout

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class HardenStdoutTest(unittest.TestCase):
    def test_gbk_console_replaces_unencodable_characters_instead_of_raising(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="gbk")  # strict errors, like a real console
        with patch.object(sys, "stdout", stream):
            harden_stdout()
            print("pipeline OK \ufffd")
            stream.flush()
        self.assertIn("pipeline OK", buffer.getvalue().decode("gbk"))

    def test_stream_without_reconfigure_is_left_alone(self):
        sink = io.StringIO()
        with patch.object(sys, "stdout", sink), patch.object(sys, "stderr", sink):
            harden_stdout()
        self.assertEqual(sink.getvalue(), "")

    def test_closed_stream_does_not_break_the_run(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="gbk")
        stream.close()
        with patch.object(sys, "stdout", stream), patch.object(sys, "stderr", stream):
            harden_stdout()


class EntryScriptTest(unittest.TestCase):
    def test_every_operator_script_hardens_the_console(self):
        """A script that prints a path or a probe detail must survive a non-UTF-8 console."""
        missing = [
            path.name
            for path in sorted(SCRIPTS.glob("*.py"))
            if "harden_stdout()" not in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
