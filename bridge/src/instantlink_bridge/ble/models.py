"""Instax printer model specifications.

Values are ported from InstantLink's `instantlink-core/src/models.rs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PrinterModel(StrEnum):
    """Supported Fujifilm Instax Link printer models."""

    MINI = "mini"
    MINI_LINK3 = "mini_link3"
    SQUARE = "square"
    WIDE = "wide"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Per-model image and transfer constraints."""

    model: PrinterModel
    width: int
    height: int
    chunk_size: int
    name: str
    max_image_size: int
    packet_delay_ms: int
    pre_execute_delay_ms: int
    success_code: int
    flip_vertical: bool


MODEL_SPECS: dict[PrinterModel, ModelSpec] = {
    PrinterModel.MINI: ModelSpec(
        model=PrinterModel.MINI,
        width=600,
        height=800,
        chunk_size=900,
        name="Instax Mini Link",
        max_image_size=105_000,
        packet_delay_ms=0,
        pre_execute_delay_ms=0,
        success_code=0,
        flip_vertical=False,
    ),
    PrinterModel.MINI_LINK3: ModelSpec(
        model=PrinterModel.MINI_LINK3,
        width=600,
        height=800,
        chunk_size=900,
        name="Instax Mini Link 3",
        max_image_size=55_000,
        packet_delay_ms=75,
        pre_execute_delay_ms=1000,
        success_code=16,
        flip_vertical=True,
    ),
    PrinterModel.SQUARE: ModelSpec(
        model=PrinterModel.SQUARE,
        width=800,
        height=800,
        chunk_size=1808,
        name="Instax Square Link",
        max_image_size=105_000,
        packet_delay_ms=150,
        pre_execute_delay_ms=1000,
        success_code=12,
        flip_vertical=False,
    ),
    PrinterModel.WIDE: ModelSpec(
        model=PrinterModel.WIDE,
        width=1260,
        height=840,
        chunk_size=900,
        name="Instax Wide Link",
        max_image_size=225_000,
        packet_delay_ms=150,
        pre_execute_delay_ms=0,
        success_code=15,
        flip_vertical=False,
    ),
}


def spec_for(model: PrinterModel) -> ModelSpec:
    """Return the model specification."""

    return MODEL_SPECS[model]


def parse_printer_model(value: str) -> PrinterModel:
    """Parse a config value into a supported printer model."""

    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "mini": PrinterModel.MINI,
        "mini_link": PrinterModel.MINI,
        "mini_link_1": PrinterModel.MINI,
        "mini_link_2": PrinterModel.MINI,
        "minilink3": PrinterModel.MINI_LINK3,
        "mini_link3": PrinterModel.MINI_LINK3,
        "mini_link_3": PrinterModel.MINI_LINK3,
        "link3": PrinterModel.MINI_LINK3,
        "square": PrinterModel.SQUARE,
        "square_link": PrinterModel.SQUARE,
        "wide": PrinterModel.WIDE,
        "wide_link": PrinterModel.WIDE,
    }
    try:
        return aliases[normalized]
    except KeyError as error:
        supported = ", ".join(model.value for model in PrinterModel)
        raise ValueError(
            f"unsupported printer model {value!r}; expected one of {supported}"
        ) from error


def detect_model(width: int, height: int, dis_model: str | None = None) -> PrinterModel:
    """Detect model from image support dimensions and optional DIS model string."""

    if dis_model and "fi033" in dis_model.casefold():
        return PrinterModel.MINI_LINK3
    match (width, height):
        case (600, 800):
            return PrinterModel.MINI
        case (800, 800):
            return PrinterModel.SQUARE
        case (1260, 840):
            return PrinterModel.WIDE
        case _:
            raise ValueError(f"unknown printer dimensions: {width}x{height}")


def is_success_status(model: PrinterModel, status: int) -> bool:
    """Return whether a printer status byte is success for this model."""

    return status in {0, spec_for(model).success_code}
