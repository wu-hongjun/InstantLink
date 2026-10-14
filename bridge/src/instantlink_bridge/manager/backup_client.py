"""Sanitized client for the fixed root-owned local backup socket."""

from __future__ import annotations

import json
import socket
from typing import cast

from instantlink_bridge.manager.backup import BackupError
from instantlink_bridge.manager.contract import JsonObject


class PrivateBackupError(BackupError):
    """Sanitized broker rejection with a stable operation error code."""

    def __init__(self, error_code: str) -> None:
        super().__init__("private backup broker rejected the operation")
        self.error_code = error_code


BACKUP_SOCKET = "/run/instantlink-bridge-backup.sock"


def request_private_backup(
    action: str, *, backup_id: str | None = None, version: str | None = None
) -> JsonObject:
    request: dict[str, str] = {"action": action}
    if backup_id is not None:
        request["backup_id"] = backup_id
    if version is not None:
        request["version"] = version
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(610)
            connection.connect(BACKUP_SOCKET)
            connection.sendall(json.dumps(request).encode("utf-8") + b"\n")
            data = bytearray()
            while not data.endswith(b"\n") and len(data) < 65536:
                packet = connection.recv(65536 - len(data))
                if not packet:
                    break
                data.extend(packet)
        response = json.loads(data)
        if (
            not isinstance(response, dict)
            or response.get("ok") is not True
            or not isinstance(response.get("payload"), dict)
        ):
            error_code = response.get("error_code") if isinstance(response, dict) else None
            raise PrivateBackupError(
                "backup_not_found" if error_code == "backup_not_found" else "backup_failed"
            )
        return cast(JsonObject, response["payload"])
    except PrivateBackupError:
        raise
    except (OSError, ValueError) as exc:
        raise BackupError("private backup broker unavailable or operation failed") from exc
