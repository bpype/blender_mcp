# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Blender addon that provides an MCP socket server.
"""

__all__ = (
    "register",
    "unregister",
)

import bpy  # pylint: disable=import-error
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty  # pylint: disable=import-error

from . import execute_interactive
from . import mcp_to_blender_server as server
from .cli import cli_execute as _cli_execute

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9876
PORT_MIN = 1024
PORT_MAX = 65535

# Default seconds to wait after registration before auto-starting the server.
# Avoids adding work to Blender's startup sequence.
AUTOSTART_DELAY = 1.0

_cli_commands: list[object] = []


class State:
    """
    Module-level runtime state that is not persisted across sessions.
    """

    # Displayed in the preferences UI when non-empty.
    autostart_error: str = ""


def state_startup_info_set(error: str) -> None:
    """
    Store a startup error message to display in the preferences UI.
    """
    State.autostart_error = error


def state_startup_info_clear() -> None:
    """
    Clear any startup error so it no longer appears in the preferences UI.
    """
    State.autostart_error = ""


class BlenderMCPPreferences(bpy.types.AddonPreferences):  # type: ignore[misc]
    bl_idname = __package__

    host: StringProperty(name="Host", default=DEFAULT_HOST)  # type: ignore[valid-type]
    port: IntProperty(name="Port", default=DEFAULT_PORT, min=PORT_MIN, max=PORT_MAX)  # type: ignore[valid-type]
    use_autostart: BoolProperty(  # type: ignore[valid-type]
        name="Auto Start",
        description=(
            "Automatically start the MCP server when Blender starts.\n"
            "(Not used in background mode)"
        ),
        default=True,
    )
    autostart_delay: FloatProperty(  # type: ignore[valid-type]
        name="Auto Start Delay",
        description=(
            "Seconds to wait after Blender starts before auto-starting the server.\n"
            "Avoids adding work to Blender's startup sequence"
        ),
        default=AUTOSTART_DELAY,
        min=0.0,
        max=30.0,
        step=10,
        precision=1,
        subtype="TIME_ABSOLUTE",
    )

    def _update_use_log(self, _context: bpy.types.Context) -> None:
        server.use_log = self.use_log

    use_log: BoolProperty(  # type: ignore[valid-type]
        name="Log",
        description="Print every tool request and response status to the terminal",
        default=False,
        update=_update_use_log,
    )

    def _update_timer_interval_active(self, _context: bpy.types.Context) -> None:
        # Cached on the server module because the timer callback may fire
        # many times a second, avoid slower preferences lookups.
        server.timer_internal_vars_calc(active=self.timer_interval_active)

    timer_interval_active: FloatProperty(  # type: ignore[valid-type]
        name="Timer Interval",
        description="Seconds between queue polling ticks in interactive mode",
        default=0.25,
        min=0.05,
        max=5.0,
        step=1,
        precision=2,
        subtype="TIME_ABSOLUTE",
        update=_update_timer_interval_active,
    )

    def _update_timer_interval_idle(self, _context: bpy.types.Context) -> None:
        # Cached on the server module because the timer callback may fire
        # many times a second, avoid slower preferences lookups.
        server.timer_internal_vars_calc(idle=self.timer_interval_idle)

    timer_interval_idle: FloatProperty(  # type: ignore[valid-type]
        name="Timer Interval Idle",
        description="Seconds between queue polling ticks while idle (no pending work)",
        default=1.0,
        min=0.1,
        max=10.0,
        step=10,
        precision=2,
        subtype="TIME_ABSOLUTE",
        update=_update_timer_interval_idle,
    )

    def _update_timer_interval_idle_delay(self, _context: bpy.types.Context) -> None:
        # Cached on the server module because the timer callback may fire
        # many times a second, avoid slower preferences lookups.
        server.timer_internal_vars_calc(idle_delay=self.timer_interval_idle_delay)

    timer_interval_idle_delay: FloatProperty(  # type: ignore[valid-type]
        name="Idle Delay",
        description="Seconds of inactivity before switching to the idle polling interval",
        default=5.0,
        min=1.0,
        max=60.0,
        step=100,
        precision=1,
        subtype="TIME_ABSOLUTE",
        update=_update_timer_interval_idle_delay,
    )

    def draw(self, context: bpy.types.Context) -> None:
        del context
        layout = self.layout
        layout.prop(self, "host")
        layout.prop(self, "port")
        layout.prop(self, "use_autostart")
        layout.prop(self, "autostart_delay")
        layout.prop(self, "timer_interval_active")
        layout.prop(self, "timer_interval_idle")
        layout.prop(self, "timer_interval_idle_delay")
        layout.prop(self, "use_log")

        if server.is_running():
            layout.operator("blmcp.server_stop", icon="CANCEL")
            layout.label(text="Server is running", icon="CHECKMARK")
        else:
            layout.operator("blmcp.server_start", icon="PLAY")
            layout.label(text="Server is stopped", icon="X")

        if State.autostart_error:
            layout.label(text=State.autostart_error, icon="ERROR")


class BLMCP_OT_server_start(bpy.types.Operator):  # type: ignore[misc]
    bl_idname = "blmcp.server_start"
    bl_label = "Start MCP Server"
    bl_description = "Start the MCP socket server"

    def execute(self, context: bpy.types.Context) -> set[str]:
        # Timers do not fire in background mode. Use the CLI command instead:
        # `blender --background file.blend --command blender_mcp`.
        if bpy.app.background:
            self.report({"ERROR"}, "Use `--command blender_mcp` to start the MCP server in background mode")
            return {"CANCELLED"}
        # Clear any stale autostart error so it does not persist in the UI.
        state_startup_info_clear()
        prefs = context.preferences.addons[__package__].preferences
        server.timer_internal_vars_calc(
            active=prefs.timer_interval_active,
            idle=prefs.timer_interval_idle,
            idle_delay=prefs.timer_interval_idle_delay,
        )
        server.use_log = prefs.use_log
        try:
            server.start(prefs.host, prefs.port)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            state_startup_info_set(str(ex))
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        bpy.app.timers.register(execute_interactive.run, first_interval=server.TIMER_INTERVAL_ACTIVE, persistent=True)
        self.report({"INFO"}, "MCP server started on {:s}:{:d}".format(prefs.host, prefs.port))
        return {"FINISHED"}


class BLMCP_OT_server_stop(bpy.types.Operator):  # type: ignore[misc]
    bl_idname = "blmcp.server_stop"
    bl_label = "Stop MCP Server"
    bl_description = "Stop the MCP socket server"

    def execute(self, context: bpy.types.Context) -> set[str]:
        del context
        # Clear any stale autostart error so it does not persist in the UI.
        state_startup_info_clear()
        server.stop()
        if bpy.app.timers.is_registered(execute_interactive.run):
            bpy.app.timers.unregister(execute_interactive.run)
        self.report({"INFO"}, "MCP server stopped")
        return {"FINISHED"}


classes = (
    BlenderMCPPreferences,
    BLMCP_OT_server_start,
    BLMCP_OT_server_stop,
)


def _autostart_timer() -> None:
    """
    Deferred timer callback that starts the server when ``use_autostart``
    is enabled. Runs after a delay to avoid slowing down Blender's startup.
    """
    prefs = bpy.context.preferences.addons[__package__].preferences
    server.timer_internal_vars_calc(
        active=prefs.timer_interval_active,
        idle=prefs.timer_interval_idle,
        idle_delay=prefs.timer_interval_idle_delay,
    )
    server.use_log = prefs.use_log
    if server.is_running():
        return
    try:
        server.start(prefs.host, prefs.port)
    except Exception as ex:  # pylint: disable=broad-exception-caught
        state_startup_info_set(str(ex))
        return
    bpy.app.timers.register(execute_interactive.run, first_interval=server.TIMER_INTERVAL_ACTIVE, persistent=True)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    _cli_commands.append(bpy.utils.register_cli_command("blender_mcp", _cli_execute))

    # Defer auto-start so the server does not slow down Blender's startup.
    if not bpy.app.background:
        prefs = bpy.context.preferences.addons[__package__].preferences
        if prefs.use_autostart:
            bpy.app.timers.register(
                _autostart_timer,
                first_interval=prefs.autostart_delay,
                persistent=True,
            )


def unregister() -> None:
    for cmd in _cli_commands:
        bpy.utils.unregister_cli_command(cmd)
    _cli_commands.clear()

    if bpy.app.timers.is_registered(_autostart_timer):
        bpy.app.timers.unregister(_autostart_timer)

    server.stop()
    if bpy.app.timers.is_registered(execute_interactive.run):
        bpy.app.timers.unregister(execute_interactive.run)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
