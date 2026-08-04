"""Plan 056 T1.1 — the preview's prepared image is reused by the print path.

Also covers the two supporting changes: the worker's backend flavour
(``apply_model_flip=False``) and the no-op copy guard in ``_exif_transposed``.
"""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from instantlink_bridge.ble.instantlink import _speculative_prepared
from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.camera.ftp import ReceivedImage
from instantlink_bridge.config import BridgeConfig, PrinterConfig
from instantlink_bridge.imaging.pipeline import (
    FitMode,
    PreparedImage,
    PrintEdit,
    UnsupportedImageError,
    _exif_transposed,
    prepare_for_instantlink_backend,
    prepare_for_instax,
)
from instantlink_bridge.imaging.postprocess import (
    AdjustmentProfile,
    _apply_hue,
    apply_adjustments,
    apply_post_fit_adjustments,
    apply_pre_fit_adjustments,
)
from instantlink_bridge.imaging.worker import ImagePreparationRequest, _run_prepare_in_child
from instantlink_bridge.ui.controller import BridgeUi
from instantlink_bridge.ui.input import NullInput
from instantlink_bridge.ui.models import PairedPrinter, UiSnapshot


class _FakeDisplay:
    def __init__(self) -> None:
        self.snapshots: list[UiSnapshot] = []

    def render(self, snapshot: UiSnapshot) -> None:
        self.snapshots.append(snapshot)

    def set_idle_stage(self, stage: str) -> None:
        return

    def close(self) -> None:
        return


class _FakePairer:
    async def list_paired(self) -> list[PairedPrinter]:
        return []


async def _unused_wifi_mode_setter(mode: object) -> None:
    raise AssertionError("wifi mode setter must not be called")


def _source_image(tmp_path: Path, size: tuple[int, int] = (900, 600)) -> Path:
    """Write a JPEG asymmetric under a vertical flip.

    A flat colour is unchanged by flipping, and a simple top/bottom split
    becomes a left/right split once FitMode.AUTO rotates a landscape source
    for a portrait frame — also flip-symmetric. Both make the flip-flavour
    assertions below pass vacuously. A block in a single corner stays
    asymmetric through any rotation.
    """

    path = tmp_path / "source.jpg"
    image = Image.new("RGB", size, (20, 30, 200))
    image.paste((220, 40, 30), (0, 0, size[0] // 3, size[1] // 3))
    image.save(path, format="JPEG", quality=90)
    return path


def _controller() -> BridgeUi:
    return BridgeUi(
        BridgeConfig(printer=PrinterConfig(model=PrinterModel.SQUARE)),
        display=_FakeDisplay(),
        input_device=NullInput(),
        pairer=_FakePairer(),
        wifi_mode_setter=_unused_wifi_mode_setter,
    )


def _prepared(model: PrinterModel = PrinterModel.SQUARE) -> PreparedImage:
    return PreparedImage(
        data=b"jpeg",
        model=model,
        width=800,
        height=800,
        quality=74,
        fit=FitMode.AUTO,
    )


# --- controller hand-off ---------------------------------------------------


def test_take_prepared_returns_image_when_edit_matches(tmp_path: Path) -> None:
    ui = _controller()
    received = ReceivedImage(tmp_path / "a.jpg", "192.168.8.10")
    edit = PrintEdit(rotate_degrees=90)
    prepared = _prepared()
    ui._prepared_print_image = prepared
    ui._prepared_print_key = (received.path, edit)

    assert ui.take_prepared_print_image(received, edit) is prepared


def test_take_prepared_is_consumed_once(tmp_path: Path) -> None:
    ui = _controller()
    received = ReceivedImage(tmp_path / "a.jpg", "192.168.8.10")
    edit = PrintEdit()
    ui._prepared_print_image = _prepared()
    ui._prepared_print_key = (received.path, edit)

    assert ui.take_prepared_print_image(received, edit) is not None
    # A second print must not reuse a stale image.
    assert ui.take_prepared_print_image(received, edit) is None


def test_take_prepared_rejects_changed_edit(tmp_path: Path) -> None:
    ui = _controller()
    received = ReceivedImage(tmp_path / "a.jpg", "192.168.8.10")
    ui._prepared_print_image = _prepared()
    ui._prepared_print_key = (received.path, PrintEdit(zoom=2.0))

    assert ui.take_prepared_print_image(received, PrintEdit()) is None


def test_take_prepared_rejects_different_source(tmp_path: Path) -> None:
    ui = _controller()
    edit = PrintEdit()
    ui._prepared_print_image = _prepared()
    ui._prepared_print_key = (tmp_path / "a.jpg", edit)

    other = ReceivedImage(tmp_path / "b.jpg", "192.168.8.10")
    assert ui.take_prepared_print_image(other, edit) is None


def test_take_prepared_without_preview_returns_none(tmp_path: Path) -> None:
    # auto_print_delay_s=0 skips the preview entirely, so nothing is cached.
    ui = _controller()
    received = ReceivedImage(tmp_path / "a.jpg", "192.168.8.10")

    assert ui.take_prepared_print_image(received, PrintEdit()) is None


def test_none_edit_matches_default_print_edit(tmp_path: Path) -> None:
    ui = _controller()
    received = ReceivedImage(tmp_path / "a.jpg", "192.168.8.10")
    prepared = _prepared()
    ui._prepared_print_image = prepared
    ui._prepared_print_key = (received.path, PrintEdit())

    assert ui.take_prepared_print_image(received, None) is prepared


# --- worker flavour --------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.sent: list[object] = []

    def send(self, value: object) -> None:
        self.sent.append(value)

    def close(self) -> None:
        return


@pytest.mark.parametrize("model", [PrinterModel.SQUARE, PrinterModel.MINI_LINK3])
def test_worker_backend_flavour_matches_print_path(tmp_path: Path, model: PrinterModel) -> None:
    """apply_model_flip=False must reproduce what the print path builds itself.

    MINI_LINK3 is the only flip_vertical model, so it is the case that would
    silently hand an upside-down image to the printer if the flavours diverged.
    """

    source = _source_image(tmp_path)
    recorder = _Recorder()
    _run_prepare_in_child(
        recorder,  # type: ignore[arg-type]
        ImagePreparationRequest(source_path=source, model=model, apply_model_flip=False),
    )

    expected = prepare_for_instantlink_backend(source, model)
    assert recorder.sent[0].prepared.data == expected.data  # type: ignore[attr-defined]


def test_worker_default_flavour_still_applies_model_flip(tmp_path: Path) -> None:
    source = _source_image(tmp_path)
    recorder = _Recorder()
    _run_prepare_in_child(
        recorder,  # type: ignore[arg-type]
        ImagePreparationRequest(source_path=source, model=PrinterModel.MINI_LINK3),
    )

    expected = prepare_for_instax(source, PrinterModel.MINI_LINK3)
    assert recorder.sent[0].prepared.data == expected.data  # type: ignore[attr-defined]


def test_flip_flavours_differ_for_flip_model(tmp_path: Path) -> None:
    # Guards the premise of the two tests above: if these ever became equal the
    # reuse in T1.1 would be trivially "correct" for the wrong reason.
    source = _source_image(tmp_path)
    flipped = prepare_for_instax(source, PrinterModel.MINI_LINK3)
    upright = prepare_for_instantlink_backend(source, PrinterModel.MINI_LINK3)

    assert flipped.data != upright.data


# --- T1.4 no-op copy guard -------------------------------------------------


def test_exif_transposed_passes_through_when_upright() -> None:
    image = Image.new("RGB", (40, 30), (10, 20, 30))

    # Same object: no full-resolution copy allocated.
    assert _exif_transposed(image) is image


def test_exif_transposed_rotates_when_tag_present(tmp_path: Path) -> None:
    path = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (40, 30), (10, 20, 30))
    exif = image.getexif()
    exif[0x0112] = 6  # rotate 90 CW
    image.save(path, format="JPEG", exif=exif)

    with Image.open(path) as loaded:
        result = _exif_transposed(loaded)
        assert result is not loaded
        assert result.size == (30, 40)


# --- T2.1 adjustment stage split -------------------------------------------


def _two_tone(size: tuple[int, int] = (800, 600)) -> Image.Image:
    # Mid-range colours: far enough from 0 and 255 that the factors below do
    # not clip, since clamping is the one non-linear step in this path.
    image = Image.new("RGB", size, (80, 150, 110))
    image.paste((140, 90, 70), (0, 0, size[0] // 2, size[1] // 2))
    return image


def test_linear_adjustments_commute_with_the_resize() -> None:
    """The premise of T2.1, asserted rather than assumed.

    Saturation and exposure are linear in the pixel values and resampling is a
    linear combination of pixels, so the two commute. That — not
    pointwise-ness — is what licenses moving them off the 8.2 MP working
    image.
    """

    profile = AdjustmentProfile(saturation=1.3, exposure=1.1)
    source = _two_tone()
    target = (200, 150)

    before = apply_adjustments(source, profile).resize(target, Image.Resampling.LANCZOS)
    after = apply_post_fit_adjustments(source.resize(target, Image.Resampling.LANCZOS), profile)

    worst = max(band[1] for band in ImageChops.difference(before, after).getextrema())
    assert worst <= 2, f"linear adjustments did not commute with resize (max delta {worst})"


def test_hue_does_not_commute_with_the_resize() -> None:
    """Why hue stays pre-fit despite being the most expensive axis.

    Hue is pointwise but non-linear (an RGB->HSV round trip), so it does not
    commute with resampling. If this ever starts passing, hue could move to
    the post-fit stage — until then, moving it would change the image rather
    than merely speed it up.
    """

    profile = AdjustmentProfile(hue=30)
    source = _two_tone()
    target = (200, 150)

    before = apply_adjustments(source, profile).resize(target, Image.Resampling.LANCZOS)
    after = _apply_hue(source.resize(target, Image.Resampling.LANCZOS), profile.hue)

    worst = max(band[1] for band in ImageChops.difference(before, after).getextrema())
    assert worst > 2, "hue now commutes with resize — see if it can move post-fit"


def test_stage_split_covers_every_axis_exactly_once() -> None:
    """Guards against an axis being dropped or applied twice by the split."""

    image = Image.new("RGB", (60, 40), (120, 90, 60))
    identity = AdjustmentProfile()

    # Each stage must no-op on a profile whose axes all belong to the other.
    linear_only = AdjustmentProfile(saturation=1.4, exposure=1.3)
    assert apply_pre_fit_adjustments(image, linear_only) is image

    structural_only = AdjustmentProfile(sharpness=1.6, vignette=40, hue=25)
    assert apply_post_fit_adjustments(image, structural_only) is image

    assert apply_pre_fit_adjustments(image, identity) is image
    assert apply_post_fit_adjustments(image, identity) is image


# --- T1.6 speculative prep -------------------------------------------------


def test_speculative_result_is_returned_on_success() -> None:
    future: Future[PreparedImage] = Future()
    prepared = _prepared()
    future.set_result(prepared)

    assert _speculative_prepared(future) is prepared


def test_speculative_failure_does_not_raise() -> None:
    """A speculative failure must never be the error the user sees.

    Returning None falls through to the synchronous prepare, which raises the
    authoritative ImagePipelineError with the normal handling around it.
    """

    future: Future[PreparedImage] = Future()
    future.set_exception(UnsupportedImageError("corrupt"))

    assert _speculative_prepared(future) is None
