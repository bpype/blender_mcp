# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Non-blocking TCP socket server that runs inside Blender.

Listens for null-byte-delimited JSON requests, executes Python code
directly in the calling thread, and returns JSON responses.
All socket operations are non-blocking so the server never blocks
Blender's main thread.
"""

__all__ = (
    "TIMER_INTERVAL_ACTIVE",
    "is_running",
    "poll",
    "poll_blocking",
    "start",
    "stop",
    "timer_idle_interval",
    "timer_idle_reset",
    "timer_internal_vars_calc",
    "use_log",
)

import json
import math
import select
import socket
import sys
import traceback

# Seconds between main-thread timer ticks.
TIMER_INTERVAL_ACTIVE = 0.05
# Seconds between main-thread timer ticks while idle (no pending work).
_TIMER_INTERVAL_IDLE = 1.0
# Seconds of inactivity before switching to the idle interval.
_TIMER_INTERVAL_IDLE_DELAY = 5.0


class _TimerState:
    """
    Mutable singleton holding timer-related runtime state.
    """

    __slots__ = (
        "interval_active",
        "interval_idle",
        "interval_idle_delay",
        "idle_countdown_reset",
        "idle_countdown",
        "client_timeout_countdown",
    )

    def __init__(self) -> None:
        self.interval_active: float = TIMER_INTERVAL_ACTIVE
        self.interval_idle: float = _TIMER_INTERVAL_IDLE
        self.interval_idle_delay: float = _TIMER_INTERVAL_IDLE_DELAY
        # Number of active-rate ticks before switching to idle.
        self.idle_countdown_reset: int = 0
        # Current countdown. When zero, `timer_idle_interval` returns idle.
        self.idle_countdown: int = 0
        # Poll ticks before an idle client is evicted.
        self.client_timeout_countdown: int = 2


_timer = _TimerState()


def timer_internal_vars_calc(
        active: float | None = None,
        idle: float | None = None,
        idle_delay: float | None = None,
) -> None:
    """
    Optionally update ``TIMER_*`` constants and recalculate internal variables.

    When keyword arguments are provided they replace the corresponding
    module-level ``TIMER_*`` value. Pass ``None`` (the default) to leave
    a value unchanged.
    """
    if active is not None:
        _timer.interval_active = active
    if idle is not None:
        _timer.interval_idle = idle
    if idle_delay is not None:
        _timer.interval_idle_delay = idle_delay
    # Round up so the delay is never shorter than requested.
    _timer.idle_countdown_reset = math.ceil(_timer.interval_idle_delay / _timer.interval_active)
    _timer.idle_countdown = _timer.idle_countdown_reset
    _timer.client_timeout_countdown = max(2, math.ceil(_CLIENT_TIMEOUT / _timer.interval_active))


def timer_idle_reset() -> None:
    """
    Signal that work was processed, resetting the idle countdown.
    """
    _timer.idle_countdown = _timer.idle_countdown_reset


def timer_idle_interval() -> float:
    """
    Return the appropriate timer interval, decrementing the idle countdown.

    Returns ``TIMER_INTERVAL_ACTIVE`` while the countdown is positive,
    then ``_TIMER_INTERVAL_IDLE`` once it reaches zero.
    """
    if _timer.idle_countdown > 0:
        _timer.idle_countdown -= 1
        return _timer.interval_active
    return _timer.interval_idle


# When True, print every request and response status to stderr.
use_log: bool = False

_MAX_REQUEST_BYTES = 10 * 1024 * 1024  # 10 MiB.
# Maximum number of queued incoming connections.
_LISTEN_BACKLOG = 5
_RECV_BUFFER_SIZE = 4096
# Seconds before a client that has not sent a complete request is closed.
_CLIENT_TIMEOUT = 10.0
# How often `poll_blocking` checks for shutdown.
_POLL_BLOCKING_TIMEOUT = 1.0

timer_internal_vars_calc()


# ---------------------------------------------------------------------------
# Client connection state.

class _Client:
    """
    Per-connection state for a client that has not yet sent a complete request.
    """

    __slots__ = (
        "conn",
        "buffer",
        "timeout",
    )

    def __init__(self, conn: socket.socket) -> None:
        self.conn: socket.socket = conn
        # Accumulates data until the null-byte delimiter is received.
        self.buffer: bytearray = bytearray()
        # Poll ticks remaining before this client is evicted.
        self.timeout: int = _timer.client_timeout_countdown


# ---------------------------------------------------------------------------
# Server state.

class _State:
    """
    Mutable singleton holding the server's runtime state.
    """

    __slots__ = (
        "sock",
        "clients",
    )

    def __init__(self) -> None:
        # The listening socket, or `None` when not running.
        self.sock: socket.socket | None = None
        # Connected clients that have not yet sent a complete request.
        self.clients: list[_Client] = []


_state = _State()


def _encode_response(response: dict[str, object]) -> bytes:
    """
    Serialize a response dict as null-byte-delimited JSON bytes.
    """
    return (json.dumps(response) + "\0").encode("utf-8")


def _execute_code(code: str) -> dict[str, object]:
    """
    Execute *code* and return a response dict.
    """
    from .weak_sandbox import WeakSandboxForLLM

    namespace: dict[str, object] = {"result": {}}
    with WeakSandboxForLLM():
        try:
            exec(code, namespace)
        except Exception:  # pylint: disable=broad-exception-caught
            return {"status": "error", "message": traceback.format_exc()}

    result = namespace["result"]
    if not isinstance(result, dict):
        return {
            "status": "error",
            "message": (
                "The `result` variable must be a dict, not {:s}. "
                "Wrap your return value: `result = {{\"key\": value}}`"
            ).format(type(result).__name__),
        }
    return {"status": "ok", "result": result}


def _handle_request(data: bytes) -> dict[str, object]:
    """
    Parse a raw request and execute it.
    """
    request = json.loads(data)
    if request.get("type") != "execute":
        return {
            "status": "error",
            "message": "Unknown request type: {!r}".format(request.get("type")),
        }
    code = request.get("code", "")
    if use_log:
        print("request:\n{:s}".format(code), file=sys.stderr)
    response = _execute_code(code)
    if use_log:
        print("response: {:s}".format(json.dumps(response, indent=2)), file=sys.stderr)
    return response


def _close_client(client: _Client) -> None:
    """
    Close a client connection and remove it from the active list.
    """
    try:
        client.conn.close()
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    try:
        _state.clients.remove(client)
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Polling (called from the execution modules).

def _accept_clients() -> None:
    """
    Accept all pending connections on the listening socket.
    """
    if _state.sock is None:
        return
    while True:
        try:
            conn, _addr = _state.sock.accept()
            conn.setblocking(False)
            _state.clients.append(_Client(conn))
        except BlockingIOError:
            break
        except OSError:
            break


def _service_clients() -> bool:
    """
    Read from all connected clients, execute complete requests.

    Return ``True`` if at least one request was executed.
    """
    did_work = False
    # Iterate over a copy since clients may be removed during the loop.
    for client in _state.clients[:]:
        # Evict clients that have not sent a complete request in time.
        client.timeout -= 1
        if client.timeout <= 0:
            try:
                err: dict[str, object] = {"status": "error", "message": "Client timed out"}
                client.conn.sendall(_encode_response(err))
            except OSError:
                pass
            _close_client(client)
            continue

        try:
            chunk = client.conn.recv(_RECV_BUFFER_SIZE)
        except BlockingIOError:
            # No data available yet.
            continue
        except OSError:
            _close_client(client)
            continue

        if not chunk:
            # Client disconnected.
            _close_client(client)
            continue

        client.buffer.extend(chunk)

        # Guard against unbounded input from a misbehaving client.
        if len(client.buffer) > _MAX_REQUEST_BYTES:
            try:
                err = {
                    "status": "error",
                    "message": "Request exceeds {:d} byte limit".format(_MAX_REQUEST_BYTES),
                }
                client.conn.sendall(_encode_response(err))
            except OSError:
                pass
            _close_client(client)
            continue

        if b"\0" not in client.buffer:
            # Request not yet complete.
            continue

        # Execute the request and send the response.
        request_data = bytes(client.buffer[:client.buffer.index(b"\0")])
        try:
            response = _handle_request(request_data)
        except Exception:  # pylint: disable=broad-exception-caught
            response = {"status": "error", "message": traceback.format_exc()}
        try:
            client.conn.sendall(_encode_response(response))
        except OSError:
            pass
        _close_client(client)
        did_work = True

    return did_work


def poll() -> bool:
    """
    Non-blocking poll: accept new connections and service existing clients.

    Return ``True`` if at least one request was executed.
    """
    _accept_clients()
    return _service_clients()


def _handle_blocking_client(conn: socket.socket) -> bool:
    """
    Handle a single client connection synchronously with blocking I/O.

    Return ``True`` if a request was executed.
    """
    conn.settimeout(_CLIENT_TIMEOUT)
    try:
        buf = bytearray()
        while b"\0" not in buf:
            chunk = conn.recv(_RECV_BUFFER_SIZE)
            if not chunk:
                # Client disconnected.
                return False
            buf.extend(chunk)
            if len(buf) > _MAX_REQUEST_BYTES:
                err: dict[str, object] = {
                    "status": "error",
                    "message": "Request exceeds {:d} byte limit".format(_MAX_REQUEST_BYTES),
                }
                conn.sendall(_encode_response(err))
                return False

        request_data = bytes(buf[:buf.index(b"\0")])
        try:
            response = _handle_request(request_data)
        except Exception:  # pylint: disable=broad-exception-caught
            response = {"status": "error", "message": traceback.format_exc()}
        conn.sendall(_encode_response(response))
        return True
    except socket.timeout:
        try:
            err = {"status": "error", "message": "Client timed out"}
            conn.sendall(_encode_response(err))
        except OSError:
            pass
        return False
    except OSError:
        return False
    finally:
        conn.close()


def poll_blocking(timeout: float = _POLL_BLOCKING_TIMEOUT) -> bool:
    """
    Block until a connection arrives (up to *timeout* seconds), then
    handle it synchronously with blocking I/O.

    For use in background mode where the GUI is not running.
    Return ``True`` if a request was executed.
    """
    if _state.sock is None:
        return False

    try:
        readable, _writable, _errored = select.select([_state.sock], [], [], timeout)
    except (OSError, ValueError):
        return False

    if not readable:
        return False

    try:
        conn, _addr = _state.sock.accept()
    except (BlockingIOError, OSError):
        return False

    return _handle_blocking_client(conn)


# ---------------------------------------------------------------------------
# Public API.

def start(host: str, port: int) -> None:
    """
    Bind the listening socket and begin accepting connections.

    This does not block. The caller must arrange for ``poll`` to be
    called periodically (see ``execute_interactive`` and
    ``execute_blocking``).
    """
    if is_running():
        raise RuntimeError("Server is already running")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        sock.bind((host, port))
        sock.listen(_LISTEN_BACKLOG)
    except OSError:
        sock.close()
        raise

    _state.sock = sock


def stop() -> None:
    """
    Close the listening socket and all client connections.
    """
    sock = _state.sock
    _state.sock = None
    if sock is not None:
        try:
            sock.close()
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    for client in _state.clients:
        try:
            client.conn.close()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
    _state.clients.clear()


def is_running() -> bool:
    """
    Return whether the server is currently listening.
    """
    return _state.sock is not None
