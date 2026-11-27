from __future__ import annotations

import unittest

from scorepipe.proof_sheet.compose import _covers, _font


def _load(name: str, size: int = 24):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return None


class CjkFontTest(unittest.TestCase):
    def test_simplified_chinese_text_gets_a_font_that_covers_it(self):
        """The cover prints the source filename; 红莲华 must not become .notdef boxes."""
        text = "Animenz - 红莲华.pdf"
        font = _font(20, text)
        self.assertTrue(_covers(font, text), f"{font.getname()} cannot draw {text!r}")

    def test_a_glyphless_face_is_not_chosen_when_a_covering_one_exists(self):
        malgun = _load("malgun.ttf")
        if malgun is None or _covers(malgun, "红"):
            self.skipTest("no Korean-only face that lacks simplified Chinese glyphs")
        chosen = _font(20, "红莲华")
        self.assertNotEqual(
            chosen.getname(),
            malgun.getname(),
            "Malgun Gothic draws 红莲华 as .notdef and must not win for Han text",
        )
        self.assertTrue(_covers(chosen, "红莲华"))

    def test_korean_and_japanese_text_keep_their_own_script_first(self):
        for text in ("Animenz - 심즈.pdf", "Animenz - ひらがな.pdf"):
            font = _font(20, text)
            if not _covers(font, text):
                self.skipTest(f"no installed font covers {text!r}")
            self.assertTrue(_covers(font, text), f"{font.getname()} cannot draw {text!r}")

    def test_latin_text_keeps_the_plain_candidates(self):
        font = _font(20, "Animenz - Gurenge.pdf")
        self.assertTrue(_covers(font, "Gurenge"))


if __name__ == "__main__":
    unittest.main()
