"""JSON payload helpers for the management /v1/config endpoints.

The bridge owns the source of truth for ``BridgeConfig`` in
``instantlink_bridge.config``. This module shapes that dataclass tree into
the stable JSON envelope the macOS app's BridgeConfig.swift expects, and
applies a partial diff payload (section -> field -> value) on top of a
loaded config to produce a new ``BridgeConfig`` for writing.

Two design rules:

1. Secrets are masked on read. The FTP password is replaced with a
   sentinel ``MASKED_PASSWORD`` value so the Mac sees "set" / "unset"
   without ever receiving the cleartext over the wire. Diff application
   treats ``None`` and the sentinel both as "leave unchanged".

2. Field-level validation errors are collected into a single
   ``ConfigValidationError`` with a ``field_errors`` map shaped like
   ``"section.field": "human-readable reason"``. The handler turns this
   into a 422 response with ``error_code = "config_validation_failed"``.
"""

from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Any, cast

from instantlink_bridge.ble.models import PrinterModel, parse_printer_model
from instantlink_bridge.config import (
    AdjustmentsConfig,
    BridgeConfig,
    DatestampFormat,
    FontSize,
    FtpConfig,
    PowerConfig,
    PrinterConfig,
    SyncConfig,
    SyncDestination,
    UiAppearance,
    UiConfig,
    UiLanguage,
    WorkflowConfig,
    parse_datestamp_format,
    parse_font_size,
    parse_ftp_receive_mode,
    parse_sync_destination,
    parse_ui_appearance,
    parse_ui_language,
)
from instantlink_bridge.imaging.pipeline import FitMode, parse_fit_mode

# Sentinel returned in place of cleartext passwords on read. Round-trips on
# PUT mean "no change" so the cleartext never leaves /etc/InstantLinkBridge.
MASKED_PASSWORD = "__MASKED__"

# Fields the Mac is allowed to edit through Phase B's typed surface. The
# diff applier rejects unknown top-level sections and unknown fields per
# section to keep the contract additive-only.
ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "ftp": frozenset(
        {
            "mode",
            "username",
            "password",
        }
    ),
    "printer": frozenset(
        {
            "model",
            "fit",
            "quality",
            "keepalive_interval_s",
            "search_interval_s",
        }
    ),
    "workflow": frozenset(
        {
            "auto_print_delay_s",
            "allow_print_without_film",
        }
    ),
    "power": frozenset(
        {
            "idle_poweroff_enabled",
            "idle_poweroff_after_s",
        }
    ),
    "ui": frozenset(
        {
            "appearance",
            "font_size",
            "language",
        }
    ),
    "adjustments": frozenset(
        {
            "preset",
            "saturation",
            "exposure",
            "sharpness",
            "hue",
            "vignette",
            "datestamp",
            "datestamp_format",
            "watermark",
            "watermark_text",
        }
    ),
    # Only the destination is runtime-adjustable; port, paths, and the
    # outbox disk budget are provisioning-level (plan 050).
    "sync": frozenset(
        {
            "destination",
        }
    ),
}


class ConfigValidationError(Exception):
    """Raised when a /v1/config PUT diff cannot be applied.

    ``field_errors`` is keyed by ``"section.field"`` with human-readable
    messages safe to surface inline next to a typed control in the Mac
    settings UI.
    """

    def __init__(self, field_errors: dict[str, str]) -> None:
        super().__init__("Configuration validation failed.")
        self.field_errors = dict(field_errors)


def serialize_config(config: BridgeConfig) -> dict[str, Any]:
    """Render a ``BridgeConfig`` as the JSON envelope returned by GET /v1/config.

    Cleartext secrets are masked. The shape is stable per the contract
    and mirrored by ``BridgeConfig.swift`` on the macOS side.
    """

    return {
        "ftp": _serialize_ftp(config.ftp),
        "printer": _serialize_printer(config.printer),
        "workflow": _serialize_workflow(config.workflow),
        "power": _serialize_power(config.power),
        "ui": _serialize_ui(config.ui),
        "adjustments": _serialize_adjustments(config.adjustments),
        "sync": _serialize_sync(config.sync),
    }


def apply_config_diff(current: BridgeConfig, diff: dict[str, Any]) -> BridgeConfig:
    """Apply a partial diff payload, returning a new ``BridgeConfig``.

    Raises ``ConfigValidationError`` with a populated ``field_errors``
    map when one or more fields are malformed or out of range.
    """

    field_errors: dict[str, str] = {}
    new_ftp = current.ftp
    new_printer = current.printer
    new_workflow = current.workflow
    new_power = current.power
    new_ui = current.ui
    new_adjustments = current.adjustments
    new_sync = current.sync

    for section, body in diff.items():
        if section not in ALLOWED_FIELDS:
            field_errors[section] = f"Unknown section: {section!r}."
            continue
        if not isinstance(body, dict):
            field_errors[section] = "Section payload must be an object."
            continue
        allowed = ALLOWED_FIELDS[section]
        for key in body:
            if key not in allowed:
                field_errors[f"{section}.{key}"] = "Field is not editable from the macOS app."

    # Stop here if any structural error was raised: we don't want to apply
    # a half-validated diff.
    if field_errors:
        raise ConfigValidationError(field_errors)

    if "ftp" in diff:
        new_ftp = _apply_ftp(current.ftp, cast(dict[str, Any], diff["ftp"]), field_errors)
    if "printer" in diff:
        new_printer = _apply_printer(
            current.printer,
            cast(dict[str, Any], diff["printer"]),
            field_errors,
        )
    if "workflow" in diff:
        new_workflow = _apply_workflow(
            current.workflow,
            cast(dict[str, Any], diff["workflow"]),
            field_errors,
        )
    if "power" in diff:
        new_power = _apply_power(
            current.power,
            cast(dict[str, Any], diff["power"]),
            field_errors,
        )
    if "ui" in diff:
        new_ui = _apply_ui(current.ui, cast(dict[str, Any], diff["ui"]), field_errors)
    if "adjustments" in diff:
        new_adjustments = _apply_adjustments(
            current.adjustments,
            cast(dict[str, Any], diff["adjustments"]),
            field_errors,
        )
    if "sync" in diff:
        new_sync = _apply_sync(current.sync, cast(dict[str, Any], diff["sync"]), field_errors)

    if field_errors:
        raise ConfigValidationError(field_errors)

    return BridgeConfig(
        ftp=new_ftp,
        printer=new_printer,
        workflow=new_workflow,
        power=new_power,
        firmware=current.firmware,
        ui=new_ui,
        adjustments=new_adjustments,
        sync=new_sync,
    )


# --- serialization ---------------------------------------------------------


def _serialize_ftp(ftp: FtpConfig) -> dict[str, Any]:
    return {
        "mode": ftp.mode.value,
        "username": ftp.username,
        # Cleartext password never leaves the bridge. The Mac surfaces a
        # "set" / "unset" pill instead of the real value.
        "password_set": bool(ftp.password) and ftp.password != "change-me",
    }


def _serialize_printer(printer: PrinterConfig) -> dict[str, Any]:
    return {
        "model": printer.model.value if printer.model is not None else "auto",
        "fit": printer.fit.value,
        "quality": printer.quality,
        "keepalive_interval_s": printer.keepalive_interval_s,
        "search_interval_s": printer.search_interval_s,
    }


def _serialize_workflow(workflow: WorkflowConfig) -> dict[str, Any]:
    delay: float | str
    if workflow.auto_print_delay_s is None:
        delay = "off"
    else:
        delay = workflow.auto_print_delay_s
    return {
        "auto_print_delay_s": delay,
        "allow_print_without_film": workflow.allow_print_without_film,
    }


def _serialize_power(power: PowerConfig) -> dict[str, Any]:
    return {
        "backend": power.backend.value,
        "idle_poweroff_enabled": power.idle_poweroff_enabled,
        "idle_poweroff_after_s": power.idle_poweroff_after_s,
    }


def _serialize_ui(ui: UiConfig) -> dict[str, Any]:
    return {
        "appearance": ui.appearance.value,
        "font_size": ui.font_size.value,
        "language": ui.language.value,
    }


def _serialize_sync(sync: SyncConfig) -> dict[str, Any]:
    return {
        "destination": sync.destination.value,
    }


def _serialize_adjustments(adj: AdjustmentsConfig) -> dict[str, Any]:
    return {
        "preset": adj.preset,
        "saturation": adj.saturation,
        "exposure": adj.exposure,
        "sharpness": adj.sharpness,
        "hue": adj.hue,
        "vignette": adj.vignette,
        "datestamp": adj.datestamp,
        "datestamp_format": adj.datestamp_format.value,
        "watermark": adj.watermark,
        "watermark_text": adj.watermark_text,
    }


# --- diff application ------------------------------------------------------


def _apply_ftp(
    current: FtpConfig,
    body: dict[str, Any],
    field_errors: dict[str, str],
) -> FtpConfig:
    mode = current.mode
    username = current.username
    password = current.password
    if "mode" in body:
        try:
            mode = parse_ftp_receive_mode(body["mode"])
        except ValueError as exc:
            field_errors["ftp.mode"] = str(exc)
    if "username" in body:
        raw = body["username"]
        if not isinstance(raw, str) or not raw.strip():
            field_errors["ftp.username"] = "Username must be a non-empty string."
        else:
            username = raw.strip()
    if "password" in body:
        raw = body["password"]
        if raw is None or raw == MASKED_PASSWORD:
            pass  # leave unchanged
        elif not isinstance(raw, str) or not raw:
            field_errors["ftp.password"] = "Password must be a non-empty string."
        else:
            password = raw
    return replace(current, mode=mode, username=username, password=password)


def _apply_printer(
    current: PrinterConfig,
    body: dict[str, Any],
    field_errors: dict[str, str],
) -> PrinterConfig:
    model: PrinterModel | None = current.model
    fit: FitMode = current.fit
    quality = current.quality
    keepalive = current.keepalive_interval_s
    search = current.search_interval_s
    if "model" in body:
        raw = body["model"]
        if raw is None or raw == "auto":
            model = None
        elif isinstance(raw, str):
            try:
                model = parse_printer_model(raw)
            except ValueError as exc:
                field_errors["printer.model"] = str(exc)
        else:
            field_errors["printer.model"] = "Model must be a string or 'auto'."
    if "fit" in body:
        raw = body["fit"]
        if isinstance(raw, str):
            try:
                fit = parse_fit_mode(raw)
            except ValueError as exc:
                field_errors["printer.fit"] = str(exc)
        else:
            field_errors["printer.fit"] = "Fit must be a string."
    if "quality" in body:
        raw = body["quality"]
        if not isinstance(raw, int) or isinstance(raw, bool):
            field_errors["printer.quality"] = "Quality must be an integer in [1, 100]."
        elif not 1 <= raw <= 100:
            field_errors["printer.quality"] = "Quality must be an integer in [1, 100]."
        else:
            quality = raw
    if "keepalive_interval_s" in body:
        keepalive = _coerce_positive_float(
            body["keepalive_interval_s"],
            field="printer.keepalive_interval_s",
            errors=field_errors,
            current=keepalive,
        )
    if "search_interval_s" in body:
        search = _coerce_positive_float(
            body["search_interval_s"],
            field="printer.search_interval_s",
            errors=field_errors,
            current=search,
        )
    return replace(
        current,
        model=model,
        fit=fit,
        quality=quality,
        keepalive_interval_s=keepalive,
        search_interval_s=search,
    )


def _apply_workflow(
    current: WorkflowConfig,
    body: dict[str, Any],
    field_errors: dict[str, str],
) -> WorkflowConfig:
    delay = current.auto_print_delay_s
    allow_no_film = current.allow_print_without_film
    if "auto_print_delay_s" in body:
        raw = body["auto_print_delay_s"]
        is_off_string = isinstance(raw, str) and raw.strip().lower() in {"off", "none", "false"}
        if raw is None or is_off_string:
            delay = None
        elif isinstance(raw, bool):
            field_errors["workflow.auto_print_delay_s"] = "Delay must be 0, 5, or 'off'."
        elif isinstance(raw, int | float):
            parsed = float(raw)
            if not isfinite(parsed) or parsed not in {0.0, 5.0}:
                field_errors["workflow.auto_print_delay_s"] = "Delay must be 0, 5, or 'off'."
            else:
                delay = parsed
        else:
            field_errors["workflow.auto_print_delay_s"] = "Delay must be 0, 5, or 'off'."
    if "allow_print_without_film" in body:
        raw = body["allow_print_without_film"]
        if isinstance(raw, bool):
            allow_no_film = raw
        else:
            field_errors["workflow.allow_print_without_film"] = "Value must be true or false."
    return replace(
        current,
        auto_print_delay_s=delay,
        allow_print_without_film=allow_no_film,
    )


def _apply_power(
    current: PowerConfig,
    body: dict[str, Any],
    field_errors: dict[str, str],
) -> PowerConfig:
    enabled = current.idle_poweroff_enabled
    poweroff_after = current.idle_poweroff_after_s
    if "idle_poweroff_enabled" in body:
        raw = body["idle_poweroff_enabled"]
        if isinstance(raw, bool):
            enabled = raw
        else:
            field_errors["power.idle_poweroff_enabled"] = "Value must be true or false."
    if "idle_poweroff_after_s" in body:
        candidate = _coerce_positive_float(
            body["idle_poweroff_after_s"],
            field="power.idle_poweroff_after_s",
            errors=field_errors,
            current=poweroff_after,
        )
        # The PowerConfig __post_init__ enforces a strictly-increasing idle
        # threshold chain. Clamp the new poweroff to >= idle_deep_after_s so
        # we don't reject otherwise reasonable user input.
        if candidate <= current.idle_deep_after_s:
            field_errors["power.idle_poweroff_after_s"] = (
                f"Must be greater than idle_deep_after_s ({current.idle_deep_after_s:g}s)."
            )
        else:
            poweroff_after = candidate
    return replace(
        current,
        idle_poweroff_enabled=enabled,
        idle_poweroff_after_s=poweroff_after,
    )


def _apply_ui(
    current: UiConfig,
    body: dict[str, Any],
    field_errors: dict[str, str],
) -> UiConfig:
    appearance: UiAppearance = current.appearance
    font_size: FontSize = current.font_size
    language: UiLanguage = current.language
    if "appearance" in body:
        try:
            appearance = parse_ui_appearance(body["appearance"])
        except ValueError as exc:
            field_errors["ui.appearance"] = str(exc)
    if "font_size" in body:
        try:
            font_size = parse_font_size(body["font_size"])
        except ValueError as exc:
            field_errors["ui.font_size"] = str(exc)
    if "language" in body:
        try:
            language = parse_ui_language(body["language"])
        except ValueError as exc:
            field_errors["ui.language"] = str(exc)
    return replace(current, appearance=appearance, font_size=font_size, language=language)


def _apply_sync(
    current: SyncConfig,
    body: dict[str, Any],
    field_errors: dict[str, str],
) -> SyncConfig:
    destination: SyncDestination = current.destination
    if "destination" in body:
        try:
            destination = parse_sync_destination(body["destination"])
        except ValueError as exc:
            field_errors["sync.destination"] = str(exc)
    return replace(current, destination=destination)


def _apply_adjustments(
    current: AdjustmentsConfig,
    body: dict[str, Any],
    field_errors: dict[str, str],
) -> AdjustmentsConfig:
    preset = current.preset
    saturation = current.saturation
    exposure = current.exposure
    sharpness = current.sharpness
    hue = current.hue
    vignette = current.vignette
    datestamp = current.datestamp
    datestamp_format: DatestampFormat = current.datestamp_format
    watermark = current.watermark
    watermark_text = current.watermark_text

    if "preset" in body:
        raw = body["preset"]
        if isinstance(raw, str):
            preset = raw
        else:
            field_errors["adjustments.preset"] = "Preset must be a string."

    for axis_name, signed in (
        ("saturation", True),
        ("exposure", True),
        ("sharpness", True),
        ("hue", True),
        ("vignette", False),
    ):
        if axis_name not in body:
            continue
        raw = body[axis_name]
        if isinstance(raw, bool) or not isinstance(raw, int):
            field_errors[f"adjustments.{axis_name}"] = (
                f"{axis_name.capitalize()} must be an integer."
            )
            continue
        low, high = (-100, 100) if signed else (0, 100)
        if not low <= raw <= high:
            field_errors[f"adjustments.{axis_name}"] = (
                f"{axis_name.capitalize()} must be in [{low}, {high}]."
            )
            continue
        if axis_name == "saturation":
            saturation = raw
        elif axis_name == "exposure":
            exposure = raw
        elif axis_name == "sharpness":
            sharpness = raw
        elif axis_name == "hue":
            hue = raw
        elif axis_name == "vignette":
            vignette = raw

    if "datestamp" in body:
        raw = body["datestamp"]
        if isinstance(raw, bool):
            datestamp = raw
        else:
            field_errors["adjustments.datestamp"] = "Datestamp must be a boolean."

    if "datestamp_format" in body:
        try:
            datestamp_format = parse_datestamp_format(body["datestamp_format"])
        except ValueError as exc:
            field_errors["adjustments.datestamp_format"] = str(exc)

    if "watermark" in body:
        raw = body["watermark"]
        if isinstance(raw, bool):
            watermark = raw
        else:
            field_errors["adjustments.watermark"] = "Watermark must be a boolean."

    if "watermark_text" in body:
        raw = body["watermark_text"]
        if raw is None:
            watermark_text = ""
        elif isinstance(raw, str):
            watermark_text = raw
        else:
            field_errors["adjustments.watermark_text"] = "Watermark text must be a string."

    # If any field-level error was raised above, AdjustmentsConfig.__post_init__
    # would re-raise on the same field; bail out and let the API layer surface
    # field_errors instead of swallowing them as a single message.
    if field_errors:
        return current
    try:
        return replace(
            current,
            preset=preset,
            saturation=saturation,
            exposure=exposure,
            sharpness=sharpness,
            hue=hue,
            vignette=vignette,
            datestamp=datestamp,
            datestamp_format=datestamp_format,
            watermark=watermark,
            watermark_text=watermark_text,
        )
    except ValueError as exc:
        # The dataclass's __post_init__ caught a residual invariant (e.g.
        # an unknown preset name); surface it as a top-level adjustments
        # error so the Mac can render the field-level state without
        # crashing.
        field_errors["adjustments"] = str(exc)
        return current


def _coerce_positive_float(
    raw: object,
    *,
    field: str,
    errors: dict[str, str],
    current: float,
) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        errors[field] = "Value must be a finite number greater than 0."
        return current
    parsed = float(raw)
    if not isfinite(parsed) or parsed <= 0:
        errors[field] = "Value must be a finite number greater than 0."
        return current
    return parsed


# Re-export commonly used helpers so consumers can import them from one module
# when wiring up Mac-side validation parity helpers later.
__all__ = [
    "ALLOWED_FIELDS",
    "MASKED_PASSWORD",
    "ConfigValidationError",
    "apply_config_diff",
    "serialize_config",
]
