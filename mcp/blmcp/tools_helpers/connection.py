# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Socket client for communicating with the Blender addon.
"""

__all__ = (
    "get_connection_params",
    "send_code",
)

import json
import os
import socket

_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 9876
_TIMEOUT = 300.0
_RECV_BUFFER_SIZE = 65536


def get_connection_params() -> tuple[str, int]:
    host = os.environ.get("BLENDER_MCP_HOST", _DEFAULT_HOST)
    port = int(os.environ.get("BLENDER_MCP_PORT", str(_DEFAULT_PORT)))
    return host, port


def send_code(code: str) -> dict[str, object]:
    """
    Send Python code to the Blender addon socket server for execution.

    Returns the value of the ``result`` variable set by the executed code.
    Raises ``ConnectionError`` when Blender is unreachable and ``RuntimeError``
    when the executed code raises an exception.
    """
    host, port = get_connection_params()
    request = json.dumps({"type": "execute", "code": code}) + "\0"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(_TIMEOUT)
        try:
            sock.connect((host, port))
        except ConnectionRefusedError as ex:
            raise ConnectionError(
                "Cannot connect to Blender at {:s}:{:d}. "
                "Ensure Blender is running with the MCP addon enabled and the server started.".format(host, port)
            ) from ex

        sock.sendall(request.encode("utf-8"))

        # Read response until the null byte delimiter.
        buf = bytearray()
        while True:
            chunk = sock.recv(_RECV_BUFFER_SIZE)
            if not chunk:
                break
            buf.extend(chunk)
            if b"\0" in buf:
                break

        if not buf:
            raise ConnectionError("Empty response from Blender")

        # Parse only up to the first null byte delimiter.
        line, _sep, _rest = buf.partition(b"\0")
        response = json.loads(line.decode("utf-8"))

        if response.get("status") == "error":
            raise RuntimeError(
                "Blender error: {:s}".format(response.get("message", "Unknown error"))
            )

        result = response.get("result")
        if not isinstance(result, dict):
            raise TypeError("Expected dict from Blender, got {!r}".format(type(result)))
        return result
