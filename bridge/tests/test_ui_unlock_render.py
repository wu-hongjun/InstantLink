from __future__ import annotations

import pytest
from PIL import ImageDraw

from instantlink_bridge.ui import render
from instantlink_bridge.ui.i18n import t
from instantlink_bridge.ui.models import UiMode, UiSnapshot
from instantlink_bridge.ui.theme import theme_for


@pytest.mark.parametrize("language", ["en", "zh-Hans"])
@pytest.mark.parametrize("font_size", ["small", "medium", "large"])
@pytest.mark.parametrize("presses", [1, 2])
def test_unlock_prompt_progress_and_text_fit(
    monkeypatch: pytest.MonkeyPatch, language: str, font_size: str, presses: int
) -> None:
    drawn: list[tuple[int, int, str, render.Font]] = []
    real_text = render._text

    def record_text(
        draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font: render.Font, fill: str
    ) -> None:
        drawn.append((x, y, text, font))
        real_text(draw, x, y, text, font, fill)

    monkeypatch.setattr(render, "_text", record_text)
    snapshot = UiSnapshot(
        mode=UiMode.UNLOCKING,
        ftp_host="192.168.8.1",
        unlock_presses=presses,
        language=language,
        font_size=font_size,
    )
    image = render.render_snapshot(snapshot, now=0)
    draw = ImageDraw.Draw(image)
    assert t("Press same button", language) in [entry[2] for entry in drawn]
    assert t("3 times to unlock", language) in [entry[2] for entry in drawn]
    remaining = "Same button twice more" if presses == 1 else "Same button once more"
    assert t(remaining, language) in [entry[2] for entry in drawn]
    assert not any("KEY" in entry[2] for entry in drawn), "Unlock must not offer menu actions"
    for x, y, text, font in drawn:
        if y >= 40:
            bounds = draw.textbbox((x, y), text, font=font)
            assert 0 <= bounds[0] < bounds[2] <= 240
            assert 40 <= bounds[1] < bounds[3] < 200
    theme = theme_for(snapshot.appearance)
    for index, x in enumerate((76, 120, 164)):
        expected = theme.accent_blue if index < presses else theme.surface
        assert image.getpixel((x, 125)) == tuple(int(expected[i : i + 2], 16) for i in (1, 3, 5))
