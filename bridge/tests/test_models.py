from __future__ import annotations

import pytest

from instantlink_bridge.ble.models import PrinterModel, detect_model, parse_printer_model, spec_for


def test_model_specs_match_instantlink_matrix() -> None:
    assert spec_for(PrinterModel.MINI).width == 600
    assert spec_for(PrinterModel.MINI).height == 800
    assert spec_for(PrinterModel.MINI).chunk_size == 900
    assert spec_for(PrinterModel.MINI).max_image_size == 105_000

    assert spec_for(PrinterModel.MINI_LINK3).flip_vertical is True
    assert spec_for(PrinterModel.MINI_LINK3).success_code == 16

    assert spec_for(PrinterModel.SQUARE).width == 800
    assert spec_for(PrinterModel.SQUARE).height == 800
    assert spec_for(PrinterModel.SQUARE).chunk_size == 1808

    assert spec_for(PrinterModel.WIDE).width == 1260
    assert spec_for(PrinterModel.WIDE).height == 840
    assert spec_for(PrinterModel.WIDE).max_image_size == 225_000


def test_detect_model_from_dimensions_and_dis_hint() -> None:
    assert detect_model(600, 800) == PrinterModel.MINI
    assert detect_model(600, 800, "FI033") == PrinterModel.MINI_LINK3
    assert detect_model(600, 800, "fi033") == PrinterModel.MINI_LINK3
    assert detect_model(800, 800) == PrinterModel.SQUARE
    assert detect_model(1260, 840) == PrinterModel.WIDE
    with pytest.raises(ValueError, match="unknown printer dimensions"):
        detect_model(1, 2)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mini", PrinterModel.MINI),
        ("mini-link-3", PrinterModel.MINI_LINK3),
        ("square link", PrinterModel.SQUARE),
        ("wide_link", PrinterModel.WIDE),
    ],
)
def test_parse_printer_model_aliases(raw: str, expected: PrinterModel) -> None:
    assert parse_printer_model(raw) == expected
