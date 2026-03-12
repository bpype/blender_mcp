# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive timer-based execution for the MCP server.

Polls client connections via ``bpy.app.timers`` so that requests are
handled in Blender's main thread during normal interactive sessions.
"""

__all__ = (
    "run",
)

from . import mcp_to_blender_server as server


def run() -> float | None:
    """
    Timer callback: poll connections, return next interval.

    Returns ``None`` when the server is no longer running, which causes
    ``bpy.app.timers`` to unregister this callback.
    """
    # While errors *should* never happen: without exception handling here,
    # any error would remove the timer - effectively breaking the add-on.
    try:
        did_work = server.poll()
    except Exception:  # pylint: disable=broad-exception-caught
        import traceback
        import sys
        print(
            "Error: unhandled exception in the MCP server timer.\n"
            "This may be a bug in Blender-MCP, as errors should not be raised at this point, continuing:\n"
            "{:s}".format(traceback.format_exc()),
            file=sys.stderr,
        )
        # This is undefined, set to true so we reset the timer.
        did_work = True

    if not server.is_running():
        return None

    if did_work:
        server.timer_idle_reset()

    return server.timer_idle_interval()
