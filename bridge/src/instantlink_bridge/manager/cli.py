"""Command line entry point for the Bridge management scaffold."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from aiohttp import web

from instantlink_bridge.config import DEFAULT_CONFIG_PATH
from instantlink_bridge.manager.api import RequestIdFactory, create_app
from instantlink_bridge.manager.auth import (
    DEFAULT_CLIENTS_DIR,
    DEFAULT_PAIRING_EXPIRY_S,
    DEFAULT_PAIRING_WINDOW_PATH,
    ClientStore,
    ConfirmationCodeFactory,
    NowSeconds,
    PairingWindowStore,
    SignedRequestVerifier,
)
from instantlink_bridge.manager.contract import (
    DEFAULT_BIND_HOSTS,
    DEFAULT_PORT,
    JsonObject,
    new_request_id,
    routes_payload,
    success_response,
)
from instantlink_bridge.manager.status import (
    collect_hello_payload,
    collect_status_payload,
)

LOGGER = logging.getLogger(__name__)
BIND_RETRY_DELAYS_S = (1.0, 2.0, 5.0, 10.0)


def main(
    argv: Sequence[str] | None = None,
    *,
    request_id_factory: RequestIdFactory = new_request_id,
    now_seconds: NowSeconds | None = None,
    confirmation_code_factory: ConfirmationCodeFactory | None = None,
) -> None:
    """Run the manager CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    pairing_store = pairing_store_from_args(
        args,
        now_seconds=now_seconds,
        confirmation_code_factory=confirmation_code_factory,
    )
    if args.command == "hello":
        emit_json(
            success_response(
                collect_hello_payload(args.config, pairing_store=pairing_store),
                request_id=request_id_factory(),
            )
        )
        return
    if args.command == "status":
        emit_json(
            success_response(
                collect_status_payload(args.config, pairing_store=pairing_store),
                request_id=request_id_factory(),
            )
        )
        return
    if args.command == "api-routes":
        emit_json(success_response(routes_payload(), request_id=request_id_factory()))
        return
    if args.command == "pairing-open":
        window = pairing_store.open_window(ttl_s=args.ttl_seconds)
        emit_json(
            success_response(
                {
                    "pairing": {
                        "open": True,
                        "confirmation_code": window.confirmation_code,
                        "expires_at": window.expires_at,
                        "expires_in_seconds": window.expires_at - window.opened_at,
                    }
                },
                request_id=request_id_factory(),
            )
        )
        return
    if args.command == "pairing-close":
        pairing_store.close_window()
        emit_json(
            success_response(
                {"pairing": {"open": False}},
                request_id=request_id_factory(),
            )
        )
        return
    if args.command == "serve":
        configure_logging(args.log_level)
        hosts = tuple(args.host) if args.host else DEFAULT_BIND_HOSTS
        validate_bind_hosts(hosts, allow_unsafe=args.allow_unsafe_bind)
        asyncio.run(
            serve(
                config_path=args.config,
                hosts=hosts,
                port=args.port,
                clients_dir=args.clients_dir,
                pairing_store=pairing_store,
                request_id_factory=request_id_factory,
            )
        )
        return
    parser.error("missing command")


def build_parser() -> argparse.ArgumentParser:
    """Build the manager CLI parser."""

    parser = argparse.ArgumentParser(description="InstantLink Bridge management API")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"config file path (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--pairing-window",
        type=Path,
        default=DEFAULT_PAIRING_WINDOW_PATH,
        help=f"pairing window file path (default: {DEFAULT_PAIRING_WINDOW_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_json_command(subparsers, "hello", "emit discovery metadata")
    add_json_command(subparsers, "status", "emit local read-only status")
    add_json_command(subparsers, "api-routes", "emit the management route catalog")

    pairing_open_parser = subparsers.add_parser(
        "pairing-open",
        help="open local management pairing and emit the confirmation code",
    )
    pairing_open_parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=DEFAULT_PAIRING_EXPIRY_S,
        help=f"pairing window lifetime (default: {DEFAULT_PAIRING_EXPIRY_S})",
    )
    pairing_open_parser.add_argument(
        "--json",
        action="store_true",
        help="emit JSON; accepted for CLI parity and currently always enabled",
    )

    pairing_close_parser = subparsers.add_parser(
        "pairing-close",
        help="close local management pairing",
    )
    pairing_close_parser.add_argument(
        "--json",
        action="store_true",
        help="emit JSON; accepted for CLI parity and currently always enabled",
    )

    serve_parser = subparsers.add_parser("serve", help="run the HTTP management API")
    serve_parser.add_argument(
        "--host",
        action="append",
        help="host/IP address to bind; may be provided more than once",
    )
    serve_parser.add_argument(
        "--allow-unsafe-bind",
        action="store_true",
        help="allow wildcard/non-Bridge management binds for development only",
    )
    serve_parser.add_argument(
        "--clients-dir",
        type=Path,
        default=DEFAULT_CLIENTS_DIR,
        help="management client record directory",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port to bind (default: {DEFAULT_PORT})",
    )
    serve_parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python logging level",
    )
    return parser


def validate_bind_hosts(hosts: Sequence[str], *, allow_unsafe: bool = False) -> None:
    """Reject wildcard management binds unless explicitly requested for development."""

    if allow_unsafe:
        return
    for host in hosts:
        if host.strip() in {"", "0.0.0.0", "::", "*"}:
            raise SystemExit(
                "Refusing unsafe management bind. Use --allow-unsafe-bind only for development."
            )


def add_json_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
) -> None:
    """Add a subcommand whose output is JSON by contract."""

    command = subparsers.add_parser(name, help=help_text)
    command.add_argument(
        "--json",
        action="store_true",
        help="emit JSON; accepted for CLI parity and currently always enabled",
    )


def emit_json(payload: JsonObject) -> None:
    """Print stable compact JSON to stdout."""

    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def pairing_store_from_args(
    args: argparse.Namespace,
    *,
    now_seconds: NowSeconds | None,
    confirmation_code_factory: ConfirmationCodeFactory | None,
) -> PairingWindowStore:
    """Build the pairing store used by local CLI commands and the API server."""

    return PairingWindowStore(
        args.pairing_window,
        now_seconds=now_seconds,
        confirmation_code_factory=confirmation_code_factory,
    )


def configure_logging(log_level: str) -> None:
    """Configure process logging for the HTTP server."""

    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def serve(
    *,
    config_path: Path,
    hosts: Sequence[str],
    port: int,
    clients_dir: Path,
    pairing_store: PairingWindowStore,
    request_id_factory: RequestIdFactory = new_request_id,
) -> None:
    """Run the aiohttp manager app until SIGINT or SIGTERM."""

    auth_verifier = SignedRequestVerifier(ClientStore(clients_dir))
    app = create_app(
        config_path=config_path,
        request_id_factory=request_id_factory,
        auth_verifier=auth_verifier,
        pairing_store=pairing_store,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    try:
        configured_hosts = tuple(dict.fromkeys(hosts))
        missing_hosts = [
            host
            for host in configured_hosts
            if not await start_listener(runner, host, port, report_failure=True)
        ]
        if len(missing_hosts) == len(configured_hosts):
            raise RuntimeError("manager could not bind any configured host")
        await retry_missing_listeners(runner, missing_hosts, port, stop_event)
        await stop_event.wait()
    finally:
        await runner.cleanup()


async def start_listener(
    runner: web.AppRunner,
    host: str,
    port: int,
    *,
    report_failure: bool = False,
) -> bool:
    """Bind exactly the configured address, including USB's local-auth boundary."""

    site = web.TCPSite(runner, host, port)
    try:
        await site.start()
    except OSError as exc:
        # aiohttp registers a site before binding its socket. Remove failed
        # attempts so startup retries cannot accumulate registered dead sites.
        await site.stop()
        if report_failure:
            LOGGER.warning("manager.bind_pending host=%s port=%s errno=%s", host, port, exc.errno)
        return False
    LOGGER.info("manager.listening host=%s port=%s", host, port)
    return True


async def retry_missing_listeners(
    runner: web.AppRunner,
    missing_hosts: Sequence[str],
    port: int,
    stop_event: asyncio.Event,
) -> None:
    """Keep healthy listeners serving while late hotspot/USB addresses appear."""

    pending = list(missing_hosts)
    attempt = 0
    while pending and not stop_event.is_set():
        delay = BIND_RETRY_DELAYS_S[min(attempt, len(BIND_RETRY_DELAYS_S) - 1)]
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
            return
        except TimeoutError:
            pass
        for host in tuple(pending):
            if stop_event.is_set():
                return
            if await start_listener(runner, host, port):
                pending.remove(host)
        attempt += 1


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Install cross-platform process-stop signal handlers."""

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop_event.set)
            continue
        signal.signal(signum, lambda _signum, _frame: stop_event.set())


if __name__ == "__main__":
    main()
