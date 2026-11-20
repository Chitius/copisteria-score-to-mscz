from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from scorepipe.producers import resolve
from scorepipe.producers.pdf import PdfTextProducer, assign_measures, extract_words

WORK = Path(__file__).parent / ".runs" / "pdf"


def make_pdf(path: Path, text: str, x: int = 100, y: int = 700) -> None:
    """A minimal one-page PDF with one line of Helvetica text."""
    content = f"BT /F1 24 Tf {x} {y} Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def pdftotext_path() -> str | None:
    found = shutil.which("pdftotext")
    if found:
        return found
    # typical poppler install shipped with TeX Live on Windows
    candidate = Path(r"S:\ProgramFiles\texlive\2024\bin\windows\pdftotext.exe")
    return str(candidate) if candidate.is_file() else None


class PdfProducerTest(unittest.TestCase):
    def test_assign_measures_uses_the_box(self):
        words = [
            {"page": 1, "text": "Allegro", "x0": 100, "y0": 700, "x1": 200, "y1": 720},
            {"page": 1, "text": "outside", "x0": 400, "y0": 100, "x1": 460, "y1": 120},
        ]
        layout = {
            "pages": [
                {
                    "page": 1,
                    "measures": [{"number": 9, "x0": 80, "y0": 690, "x1": 260, "y1": 730}],
                }
            ]
        }
        marks = assign_measures(words, layout)
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0]["measure"], 9)
        self.assertEqual(marks[0]["text"], "Allegro")

    def test_extract_words_from_a_synthetic_pdf(self):
        binary = pdftotext_path()
        if binary is None:
            self.skipTest("pdftotext is not available")
        WORK.mkdir(parents=True, exist_ok=True)
        pdf = WORK / "one.pdf"
        make_pdf(pdf, "Allegro")
        words = extract_words(pdf, binary)
        self.assertTrue(any(word["text"] == "Allegro" for word in words), words)

        layout = {"pages": [{"page": 1, "measures": [{"number": 3, "x0": 0, "y0": 0, "x1": 612, "y1": 792}]}]}
        marks = PdfTextProducer(pdf, layout=layout, pdftotext=binary).produce(Path("unused")).marks
        self.assertTrue(any(mark["measure"] == 3 and mark["text"] == "Allegro" for mark in marks))

    def test_resolve_returns_a_pdf_producer(self):
        self.assertIsInstance(resolve("x.pdf", layout={"pages": []}), PdfTextProducer)


if __name__ == "__main__":
    unittest.main()
