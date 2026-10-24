"""Design-token conformance gate for the SchoolTwin player.

The design gate fails if:
  - any text token is below 4.5:1 on any surface, or
  - any meaning colour is below 3:1 on surface-1,
for both the ivory (default) and ink (alternate) themes; if the ink header
chrome's scoped tokens fail the same floors on their nav surfaces; or if the
canvas token map in player.js drifts from the CSS custom properties (canvas
2D cannot read CSS vars, so parity is enforced by test).
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "player" / "player.css").read_text(encoding="utf-8")
JS = (ROOT / "player" / "player.js").read_text(encoding="utf-8")


def _rel_lum(hex_str: str) -> float:
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    la, lb = _rel_lum(a), _rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _theme_block(marker: str) -> dict:
    """Extract custom-property values from one theme block of player.css."""
    start = CSS.index(marker)
    end = CSS.index("}", start)
    block = CSS[start:end]
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9A-Fa-f]{6})", block))


DARK = _theme_block('[data-theme="dark"]')
LIGHT = _theme_block(':root, [data-theme="light"]')

TEXT_TOKENS = ["--text-primary", "--text-secondary", "--text-muted"]
SURFACES = ["--bg-base", "--bg-surface", "--bg-surface-elevated", "--bg-card",
            "--bg-card-hover", "--bg-card-active", "--bg-input"]
MEANING = ["--origin-vermilion", "--affected-amber", "--secondary-pale-amber",
           "--response-teal", "--scenario-violet", "--control-sky",
           "--baseline-slate", "--status-ok", "--status-bad", "--accent"]


class TestDarkThemeContrast(unittest.TestCase):
    def test_every_text_token_meets_aa_on_every_surface(self):
        worst = []
        for t in TEXT_TOKENS:
            for s in SURFACES:
                ratio = contrast(DARK[t], DARK[s])
                worst.append((ratio, t, s))
                self.assertGreaterEqual(
                    ratio, 4.5,
                    f"dark {t} on {s} is {ratio:.2f}:1, below the 4.5:1 AA floor")
        worst.sort()
        # The design analysis promises a minimum of ~4.55:1 — hold it.
        self.assertGreaterEqual(worst[0][0], 4.5)

    def test_every_meaning_colour_visible_on_surface_1(self):
        for m in MEANING:
            ratio = contrast(DARK[m], DARK["--bg-surface"])
            self.assertGreaterEqual(
                ratio, 3.0,
                f"dark {m} on surface-1 is {ratio:.2f}:1, below the 3:1 graphics floor")


class TestLightThemeContrast(unittest.TestCase):
    def test_every_text_token_meets_aa_on_every_surface(self):
        for t in TEXT_TOKENS:
            for s in SURFACES:
                ratio = contrast(LIGHT[t], LIGHT[s])
                self.assertGreaterEqual(
                    ratio, 4.5,
                    f"light {t} on {s} is {ratio:.2f}:1, below the 4.5:1 AA floor")

    def test_every_meaning_colour_visible_on_surface_1(self):
        for m in MEANING:
            ratio = contrast(LIGHT[m], LIGHT["--bg-surface"])
            self.assertGreaterEqual(
                ratio, 3.0,
                f"light {m} on surface-1 is {ratio:.2f}:1, below the 3:1 graphics floor")


def _top_scope_block() -> dict:
    """Custom-property overrides declared inside the #top rule (ink chrome)."""
    i = CSS.index("#top {")
    j = CSS.index(chr(10) + "}", i)   # end of the #top rule (newline + brace)
    block = CSS[i:j]
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9A-Fa-f]{6})", block))


class TestInkHeaderChromeContrast(unittest.TestCase):
    """The #top scoped inversion re-maps tokens for ink chrome in both themes;
    its effective values must hold the same AA floors on nav surfaces."""

    def test_nav_tokens_meet_aa_on_nav_surfaces(self):
        for theme_block in (LIGHT, DARK):
            top = _top_scope_block()
            self.assertTrue(top, "#top scoped token block not found")
            surfaces = [theme_block["--nav-bg"], theme_block["--nav-card"],
                        theme_block["--nav-card-hover"]]
            for t in ("--nav-text", "--nav-muted"):
                for sf in surfaces:
                    ratio = contrast(theme_block[t], sf)
                    self.assertGreaterEqual(
                        ratio, 4.5,
                        f"nav {t} on {sf} is {ratio:.2f}:1, below AA")
            # the header's remapped accent (light cobalt) as text on nav cards
            for sf in surfaces:
                ratio = contrast(top["--accent"], sf)
                self.assertGreaterEqual(
                    ratio, 4.5,
                    f"#top --accent {top['--accent']} on {sf} is {ratio:.2f}:1, below AA")
            # non-text accent indicators only need the 3:1 graphics floor
            for sf in (theme_block["--nav-bg"], theme_block["--nav-bg-2"]):
                ratio = contrast(top["--accent"], sf)
                self.assertGreaterEqual(
                    ratio, 3.0,
                    f"#top --accent on {sf} is {ratio:.2f}:1, below graphics floor")


class TestCanvasTokenParity(unittest.TestCase):
    """Canvas renderers consume CANVAS_THEMES in player.js; those hexes must
    equal the CSS tokens so DOM and canvas stay one design system."""

    def _canvas_theme(self, name: str) -> dict:
        m = re.search(rf"{name}:\s*\{{(.*?)\}}", JS, re.S)
        self.assertIsNotNone(m, f"CANVAS_THEMES.{name} missing from player.js")
        return dict(re.findall(r"(\w+):\s*'(#\[0-9A-Fa-f\]{6}|#[0-9A-Fa-f]{6})'", m.group(1)))

    def test_dark_canvas_tokens_match_css(self):
        c = self._canvas_theme("dark")
        css = DARK
        pairs = {
            "canvasBg": "--bg-base", "floor": "--bg-surface", "floorBorder": "--border-default",
            "zoneDefault": "--bg-card", "playhead": "--canvas-playhead",
            "origin": "--origin-vermilion", "affected": "--affected-amber",
            "secondary": "--secondary-pale-amber", "response": "--response-teal",
            "scenario": "--scenario-violet", "control": "--control-sky",
            "baseline": "--baseline-slate", "accent": "--accent",
            "better": "--status-ok", "worse": "--status-bad",
        }
        for js_key, css_key in pairs.items():
            self.assertEqual(c.get(js_key), css.get(css_key),
                             f"canvas token {js_key} != CSS {css_key}")

    def test_light_canvas_tokens_exist_and_differ_from_dark(self):
        light = self._canvas_theme("light")
        dark = self._canvas_theme("dark")
        self.assertTrue(light)
        for k in ("origin", "affected", "response", "scenario", "control"):
            self.assertIn(k, light)
            self.assertNotEqual(light[k], dark[k], f"{k} must be re-toned for light theme")


class TestOfflineFirst(unittest.TestCase):
    def test_no_remote_font_or_cdn_imports(self):
        self.assertNotIn("@import", CSS, "player.css must not @import remote fonts (offline-first)")
        self.assertNotIn("fonts.googleapis", CSS)
        self.assertNotIn("fonts.googleapis", JS)

    def test_hatch_texture_token_defined(self):
        self.assertIn("--hatch", CSS, "hatch texture token (§7.2) must exist")

    def test_status_badge_vocabulary_present(self):
        for cls in (".badge-computed", ".badge-configured", ".badge-assumed",
                    ".badge-unmodeled", ".badge-unavailable", ".badge-ai"):
            self.assertIn(cls, CSS, f"status vocabulary class {cls} missing")


if __name__ == "__main__":
    unittest.main()
