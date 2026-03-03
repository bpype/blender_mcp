# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Integration test for the full MCP pipeline.

Requires ``BLENDER_BIN`` and ``BLENDER_MCP`` environment variables.
Run with::

    BLENDER_BIN=/path/to/blender BLENDER_MCP=/path/to/blender-mcp \
        python -m unittest tests.test_background_server -v

Foreground and interactive tests run headless via a Wayland display
server (weston). Set ``BLENDER_MCP_FOREGROUND=1`` to use the real
display instead.
"""

__all__ = ()

import glob
import json
import os
import shlex
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unittest

import sys

import atexit

# Root of the repository.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Ensure the repository root is on the path so `tests` resolves as a package.
if _REPO_DIR not in sys.path:
    sys.path.insert(0, _REPO_DIR)

from tests.mcp_client import MCPClient

# Fixed ports for the test servers (background and foreground).
_PORT_BACKGROUND = 9876
_PORT_FOREGROUND = 9877
_PORT_INTERACTIVE = 9878

# Maximum time to wait for Blender to start (seconds).
_TIMEOUT_STARTUP = 30

# Tool coverage tracking.
_all_tools: set[str] = set()
_tested_tools: set[str] = set()


def _print_untested_tools() -> None:
    """
    Print tools that were not exercised by any test.
    """
    untested = sorted(_all_tools - _tested_tools)
    if not untested:
        return
    print("\nUntested tools ({:d}/{:d}):".format(len(untested), len(_all_tools)))
    for name in untested:
        print("  - {:s}".format(name))


atexit.register(_print_untested_tools)


def _blender_env(tmpdir: str) -> dict[str, str]:
    """
    Return an environment dict for Blender sub-processes.

    Sets ``HOME`` to *tmpdir* so that Blender reads and writes its
    configuration there instead of touching the real user directory.
    Disables ASAN leak checking so debug builds exit cleanly.
    """
    env = os.environ.copy()
    env["HOME"] = tmpdir
    env["ASAN_OPTIONS"] = ":".join(filter(None, [
        env.get("ASAN_OPTIONS", ""),
        "alloc_dealloc_mismatch=0",
        "leak_check_at_exit=0",
    ]))
    return env


def _run_blender(args: list[str], env: dict[str, str]) -> None:
    """
    Run a Blender command and raise on failure, including stderr in the message.
    """
    result = subprocess.run(args, capture_output=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed (exit {:d}):\n  {:s}\n{:s}".format(
                result.returncode,
                " ".join(args),
                result.stderr.decode("utf-8", errors="replace"),
            )
        )


def _drain_stdout(proc: "subprocess.Popen[bytes]") -> None:
    """
    Read and discard *proc* stdout in a daemon thread.

    This prevents the pipe buffer from filling up and blocking the child.
    """
    def _reader() -> None:
        assert proc.stdout is not None
        for _line in proc.stdout:
            pass

    threading.Thread(target=_reader, daemon=True).start()


def _start_headless_display(env: dict[str, str]) -> "subprocess.Popen[bytes]":
    """
    Start a headless Wayland display server and add ``WAYLAND_DISPLAY`` to *env*.

    Returns the weston process. The caller must call
    ``_stop_headless_display`` when done.
    """
    from tests.utils.blender_headless import backend_wayland

    weston_socket = "wl-blmcp-{:d}".format(os.getpid())
    weston_bin = os.environ.get("WESTON_BIN", "weston")
    weston_env, weston_ini = backend_wayland._weston_env_and_ini()

    ini_fd, ini_path = tempfile.mkstemp(prefix="weston_", suffix=".ini")
    with os.fdopen(ini_fd, "w", encoding="utf-8") as fh:
        fh.write(weston_ini)

    cmd = [
        weston_bin,
        "--socket={:s}".format(weston_socket),
        "--backend=headless",
        "--width=800",
        "--height=600",
        "--config={:s}".format(ini_path),
    ]
    weston_kw: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if weston_env is not None:
        weston_kw["env"] = weston_env

    proc = subprocess.Popen(cmd, **weston_kw)

    if not backend_wayland._wait_for_wayland_server(
        socket=weston_socket, timeout=5.0,
    ):
        proc.send_signal(signal.SIGINT)
        proc.communicate()
        os.remove(ini_path)
        raise RuntimeError("Failed to start headless Wayland display server")

    env["WAYLAND_DISPLAY"] = weston_socket
    # Store for cleanup.
    proc._weston_ini_path = ini_path  # type: ignore[attr-defined]
    return proc


def _stop_headless_display(proc: "subprocess.Popen[bytes]") -> None:
    """
    Stop the headless Wayland display server started by ``_start_headless_display``.
    """
    proc.send_signal(signal.SIGINT)
    proc.communicate(timeout=10)
    ini_path = getattr(proc, "_weston_ini_path", None)
    if ini_path is not None and os.path.exists(ini_path):
        os.remove(ini_path)


def _wait_for_port(port: int, timeout: int, proc: "subprocess.Popen[bytes]") -> None:
    """
    Block until a TCP connection to *port* on localhost succeeds.

    Checks *proc* on each iteration so an early crash is reported
    immediately instead of waiting for the full timeout.
    Raises ``RuntimeError`` if *timeout* seconds elapse or *proc* exits.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            raise RuntimeError(
                "Blender exited with code {:d} before the server became reachable".format(rc)
            )
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                sock.connect(("localhost", port))
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)
    raise RuntimeError(
        "Port {:d} not reachable within {:d}s".format(port, timeout)
    )


class _TestServerMixin:
    """
    Shared setup, cleanup, helpers and test methods for both background
    and foreground server modes.

    Concrete subclasses set ``_background`` and ``_port`` as class variables.
    """

    _background: bool
    _interactive: bool = False
    _port: int

    @classmethod
    def setUpClass(cls) -> None:
        blender_bin = os.environ["BLENDER_BIN"]
        blender_mcp = os.environ["BLENDER_MCP"]

        cls._tmpdir = tempfile.TemporaryDirectory()
        tmpdir = cls._tmpdir.name
        cls.addClassCleanup(cls._tmpdir.cleanup)

        env = _blender_env(tmpdir)

        # Build the extension zip.
        addon_src = os.path.join(_REPO_DIR, "addon", "blender_mcp_addon")
        _run_blender(
            [
                blender_bin, "--command", "extension", "build",
                "--source-dir=" + addon_src,
                "--output-dir=" + tmpdir,
            ],
            env=env,
        )

        zips = glob.glob(os.path.join(tmpdir, "blender_mcp_addon-*.zip"))
        if not zips:
            raise RuntimeError("Extension build did not produce a zip")

        # Install the extension into the isolated HOME.
        _run_blender(
            [
                blender_bin, "--online-mode", "--background", "--factory-startup",
                "--command", "extension", "install-file",
                zips[0], "--repo", "user_default", "--enable",
            ],
            env=env,
        )

        if cls._interactive:
            # Save preferences before launching so the autostart timer
            # reads the correct port with no delay.
            # This could be supported more generically by passing arbitrary
            # preference overrides, but port and delay are all we need for now.
            _run_blender(
                [
                    blender_bin, "--background",
                    "--python-expr",
                    (
                        "import bpy; "
                        "prefs = bpy.context.preferences.addons"
                        "['bl_ext.user_default.blender_mcp_addon'].preferences; "
                        "prefs.port = {:d}; "
                        "prefs.autostart_delay = 0.0; "
                        "bpy.ops.wm.save_userpref()"
                    ).format(cls._port),
                ],
                env=env,
            )

        # Start a headless display server for non-background tests.
        # Registered before Blender so cleanup order is Blender first,
        # then the display server (LIFO).
        if not cls._background and not os.environ.get("BLENDER_MCP_FOREGROUND"):
            cls._weston_proc = _start_headless_display(env)
            cls.addClassCleanup(_stop_headless_display, cls._weston_proc)

        # Start Blender with the installed addon.
        # Omit `--factory-startup` so saved preferences (with the
        # extension enabled) are loaded from the isolated HOME.
        blender_args = [blender_bin, "--online-mode"]
        if cls._background:
            blender_args.append("--background")
        if not cls._interactive:
            blender_args.extend([
                "--command", "blender_mcp", "--port", str(cls._port),
            ])

        cls._blender_proc = subprocess.Popen(
            blender_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        cls.addClassCleanup(cls._cleanup_blender)

        _drain_stdout(cls._blender_proc)
        _wait_for_port(cls._port, _TIMEOUT_STARTUP, cls._blender_proc)

        mcp_env = _blender_env(tmpdir)
        mcp_env["BLENDER_MCP_PORT"] = str(cls._port)
        mcp_env["BLENDER_PATH"] = blender_bin

        cls._client = MCPClient(shlex.split(blender_mcp), env=mcp_env)
        cls.addClassCleanup(cls._client.close)
        cls._client.initialize()
        _all_tools.update(cls._client.list_tools())

        # Save a blend file for CLI tools.
        cls._blend_path = os.path.join(tmpdir, "test.blend")
        cls._client.call_tool("execute_blender_code", {
            "code": (
                "import bpy\n"
                "bpy.ops.wm.save_as_mainfile(filepath={!r})\n"
                "result = {{'saved': True}}\n"
            ).format(cls._blend_path),
        })

    @classmethod
    def _cleanup_blender(cls) -> None:
        """
        Terminate Blender and close its stdout pipe.
        """
        cls._blender_proc.terminate()
        cls._blender_proc.wait(timeout=10)
        if cls._blender_proc.stdout is not None:
            cls._blender_proc.stdout.close()

    def _call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        """
        Call a tool, verify the response is not an error, and return the content list.
        """
        _tested_tools.add(name)
        result = self._client.call_tool(name, arguments)
        content = result.get("content", [])
        self.assertFalse(
            result.get("isError", False),
            "Tool {:s} returned an error: {!r}".format(name, content),
        )
        self.assertIsInstance(content, list)
        self.assertTrue(
            len(content) > 0,
            "Expected at least one content item for {:s}".format(name),
        )
        return content

    def _call_tool_expect_error(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        """
        Call a tool and assert that the response is an MCP-level error.
        """
        _tested_tools.add(name)
        result = self._client.call_tool(name, arguments)
        self.assertTrue(
            result.get("isError", False),
            "Expected {:s} to return isError".format(name),
        )
        return result.get("content", [])

    def _test_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """
        Call a tool that returns text and return the parsed JSON result.
        """
        content = self._call_tool(name, arguments)
        text_item = content[0]
        self.assertEqual(
            text_item.get("type"), "text",
            "Expected text content for {:s}, got {!r}".format(
                name, text_item.get("type"),
            ),
        )
        return json.loads(text_item["text"])

    # -----------------------------------------------------------------
    # Interactive tools.

    def test_execute_blender_code(self) -> None:
        data = self._test_tool("execute_blender_code", {
            "code": "result = {'value': 1 + 1}",
        })
        self.assertEqual(data["value"], 2)

    def test_get_blendfile_summary_datablocks(self) -> None:
        data = self._test_tool("get_blendfile_summary_datablocks")
        self.assertEqual(data["scene_name"], "Scene")
        self.assertIn("Layout", data["workspaces"])
        self.assertIsInstance(data["datablock_counts"], dict)

    def test_get_blendfile_summary_missing_files(self) -> None:
        data = self._test_tool("get_blendfile_summary_missing_files")
        self.assertIsInstance(data["missing_files"], list)
        self.assertEqual(data["missing_files"], [])

    def test_get_blendfile_summary_of_linked_libraries(self) -> None:
        data = self._test_tool("get_blendfile_summary_of_linked_libraries")
        self.assertEqual(data["total_library_count"], 0)
        self.assertEqual(data["direct_libraries"], [])
        self.assertEqual(data["indirect_libraries"], [])

    def test_get_blendfile_summary_path_info(self) -> None:
        data = self._test_tool("get_blendfile_summary_path_info")
        self.assertTrue(data["is_saved"])
        self.assertEqual(data["filepath"], self._blend_path)

    def test_get_blendfile_summary_usage_guess(self) -> None:
        data = self._test_tool("get_blendfile_summary_usage_guess")
        guesses = data["usage_guesses"]
        self.assertIn("Animation", guesses)
        self.assertIn("Modeling", guesses)
        for scores in guesses.values():
            self.assertIn("score", scores)
            self.assertIn("certainty", scores)

    def test_get_screenshot_of_window_as_image(self) -> None:
        content = self._call_tool("get_screenshot_of_window_as_image")
        self.assertEqual(content[0].get("type"), "image")
        self.assertTrue(len(content[0].get("data", "")) > 0)

    def test_get_screenshot_of_window_as_json(self) -> None:
        data = self._test_tool("get_screenshot_of_window_as_json")
        self.assertEqual(data["scene"], "Scene")
        self.assertIsInstance(data["areas"], list)
        self.assertTrue(len(data["areas"]) > 0)
        self.assertIsNotNone(data["active_object"])
        self.assertIn("name", data["active_object"])

    # -----------------------------------------------------------------
    # CLI tools.

    def test_execute_blender_code_for_cli(self) -> None:
        data = self._test_tool("execute_blender_code_for_cli", {
            "blend_file": self._blend_path,
            "code": "result = {'version': 1}",
        })
        self.assertEqual(data["version"], 1)

    def test_get_blendfile_summary_datablocks_for_cli(self) -> None:
        data = self._test_tool("get_blendfile_summary_datablocks_for_cli", {
            "blend_file": self._blend_path,
        })
        self.assertEqual(data["scene_name"], "Scene")
        self.assertIsInstance(data["datablock_counts"], dict)

    def test_get_blendfile_summary_missing_files_for_cli(self) -> None:
        data = self._test_tool("get_blendfile_summary_missing_files_for_cli", {
            "blend_file": self._blend_path,
        })
        self.assertEqual(data["missing_files"], [])

    def test_get_blendfile_summary_of_linked_libraries_for_cli(self) -> None:
        data = self._test_tool("get_blendfile_summary_of_linked_libraries_for_cli", {
            "blend_file": self._blend_path,
        })
        self.assertEqual(data["total_library_count"], 0)

    def test_get_blendfile_summary_path_info_for_cli(self) -> None:
        data = self._test_tool("get_blendfile_summary_path_info_for_cli", {
            "blend_file": self._blend_path,
        })
        self.assertTrue(data["is_saved"])
        self.assertTrue(data["filepath"].endswith(".blend"))

    def test_get_blendfile_summary_usage_guess_for_cli(self) -> None:
        data = self._test_tool("get_blendfile_summary_usage_guess_for_cli", {
            "blend_file": self._blend_path,
        })
        guesses = data["usage_guesses"]
        self.assertIn("Animation", guesses)
        self.assertIn("Modeling", guesses)

    # -----------------------------------------------------------------
    # Object inspection tools.

    def test_get_object_detail_summary(self) -> None:
        data = self._test_tool("get_object_detail_summary", {"name": "Cube"})
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["name"], "Cube")
        self.assertEqual(data["type"], "MESH")
        self.assertEqual(data["data_name"], "Cube")
        self.assertEqual(data["location"], [0.0, 0.0, 0.0])
        self.assertEqual(data["rotation"], [0.0, 0.0, 0.0])
        self.assertEqual(data["scale"], [1.0, 1.0, 1.0])
        self.assertEqual(data["dimensions"], [2.0, 2.0, 2.0])
        self.assertIsNone(data["parent"])
        self.assertEqual(data["children"], [])
        self.assertEqual(data["modifiers"], [])
        self.assertEqual(data["constraints"], [])
        self.assertEqual(data["materials"], ["Material"])
        self.assertEqual(data["visibility"], {
            "hide_viewport": False,
            "hide_render": False,
            "hide_get": False,
        })
        self.assertIn("Collection", data["collections"])

    def test_get_object_detail_summary_error(self) -> None:
        data = self._test_tool("get_object_detail_summary", {"name": "NonExistent"})
        self.assertEqual(data["status"], "error")
        self.assertIn("'NonExistent' not found", data["message"])
        self.assertIn("Cube", data["message"])

    # -----------------------------------------------------------------
    # Navigation tools.

    def test_jump_to_tab_by_name(self) -> None:
        data = self._test_tool("jump_to_tab_by_name", {"name": "Layout"})
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["workspace"], "Layout")

    def test_jump_to_tab_by_space_type(self) -> None:
        data = self._test_tool("jump_to_tab_by_space_type", {"space_type": "VIEW_3D"})
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["space_type"], "VIEW_3D")

    def test_jump_to_view3d_object_by_name(self) -> None:
        data = self._test_tool("jump_to_view3d_object_by_name", {"name": "Cube"})
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["object"], "Cube")
        self.assertEqual(data["type"], "MESH")

    def test_jump_to_view3d_object_data_by_name(self) -> None:
        data = self._test_tool("jump_to_view3d_object_data_by_name", {"name": "Cube"})
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["data_name"], "Cube")
        self.assertEqual(data["type"], "MESH")

    # -----------------------------------------------------------------
    # Render tools.

    def _assert_valid_png(self, filepath: str) -> None:
        """
        Ask Blender to verify that *filepath* is a valid PNG file.
        """
        data = self._test_tool("execute_blender_code", {
            "code": (
                "import os\n"
                "with open({!r}, 'rb') as fh:\n"
                "    header = fh.read(8)\n"
                "result = {{\n"
                "    'size': os.path.getsize({!r}),\n"
                "    'png_magic': header == b'\\x89PNG\\r\\n\\x1a\\n',\n"
                "}}\n"
            ).format(filepath, filepath),
        })
        self.assertGreater(data["size"], 0)
        self.assertTrue(data["png_magic"])

    def test_render_thumbnail_to_path(self) -> None:
        data = self._test_tool("render_thumbnail_to_path", {
            "output_path": "thumb.png",
        })
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["filepath"].endswith("thumb.png"))
        self._assert_valid_png(data["filepath"])

    def test_render_viewport_to_path(self) -> None:
        data = self._test_tool("render_viewport_to_path", {
            "output_path": "render.png",
        })
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["filepath"].endswith("render.png"))
        self._assert_valid_png(data["filepath"])

    # -----------------------------------------------------------------
    # Error handling.

    def test_execute_blender_code_error(self) -> None:
        self._call_tool_expect_error("execute_blender_code", {
            "code": "raise ValueError('test error')",
        })

    def test_jump_to_tab_by_name_error(self) -> None:
        data = self._test_tool("jump_to_tab_by_name", {"name": "NonExistent"})
        self.assertEqual(data["status"], "error")
        self.assertIsInstance(data["available_workspaces"], list)

    def test_execute_blender_code_for_cli_error(self) -> None:
        self._call_tool_expect_error("execute_blender_code_for_cli", {
            "blend_file": self._blend_path,
            "code": "raise ValueError('cli test error')",
        })

    def test_jump_to_view3d_object_by_name_error(self) -> None:
        data = self._test_tool("jump_to_view3d_object_by_name", {"name": "NonExistent"})
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "Object 'NonExistent' not found")

    def test_jump_to_view3d_object_data_by_name_error(self) -> None:
        data = self._test_tool("jump_to_view3d_object_data_by_name", {"name": "NonExistent"})
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "No object found with data named 'NonExistent'")

    # -----------------------------------------------------------------
    # State verification.

    def test_jump_to_view3d_object_by_name_allow_edits(self) -> None:
        """
        Verify that ``allow_edits`` un-hides a hidden object.
        """
        # Hide the default Cube.
        self._test_tool("execute_blender_code", {
            "code": (
                "import bpy\n"
                "bpy.data.objects['Cube'].hide_viewport = True\n"
                "result = {'hidden': True}\n"
            ),
        })
        # Jump to it with allow_edits enabled.
        data = self._test_tool("jump_to_view3d_object_by_name", {
            "name": "Cube", "allow_edits": True,
        })
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["object"], "Cube")
        # Verify the object is no longer hidden.
        check = self._test_tool("execute_blender_code", {
            "code": (
                "import bpy\n"
                "result = {'hide_viewport': bpy.data.objects['Cube'].hide_viewport}\n"
            ),
        })
        self.assertFalse(check["hide_viewport"])

    def test_jump_to_view3d_object_data_by_name_allow_edits(self) -> None:
        """
        Verify that ``allow_edits`` un-hides an object found by data name.
        """
        # Hide the default Cube.
        self._test_tool("execute_blender_code", {
            "code": (
                "import bpy\n"
                "bpy.data.objects['Cube'].hide_viewport = True\n"
                "result = {'hidden': True}\n"
            ),
        })
        # Jump to it via data name with allow_edits enabled.
        data = self._test_tool("jump_to_view3d_object_data_by_name", {
            "name": "Cube", "allow_edits": True,
        })
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["data_name"], "Cube")
        # Verify the object is no longer hidden.
        check = self._test_tool("execute_blender_code", {
            "code": (
                "import bpy\n"
                "result = {'hide_viewport': bpy.data.objects['Cube'].hide_viewport}\n"
            ),
        })
        self.assertFalse(check["hide_viewport"])

    def test_execute_blender_code_stateful(self) -> None:
        """
        Verify that the Blender session is stateful across tool calls.
        """
        # Create an object.
        self._test_tool("execute_blender_code", {
            "code": (
                "import bpy\n"
                "bpy.ops.mesh.primitive_ico_sphere_add()\n"
                "bpy.context.active_object.name = 'TestSphere'\n"
                "result = {'created': True}\n"
            ),
        })
        # Verify it exists in a separate call.
        data = self._test_tool("execute_blender_code", {
            "code": "import bpy\nresult = {'found': 'TestSphere' in bpy.data.objects}\n",
        })
        self.assertTrue(data["found"])


# -----------------------------------------------------------------------------
# Concrete test classes.

@unittest.skipUnless(
    os.environ.get("BLENDER_BIN") and os.environ.get("BLENDER_MCP"),
    "BLENDER_BIN and BLENDER_MCP environment variables must be set",
)
class TestBackgroundServer(_TestServerMixin, unittest.TestCase):
    """
    Run all tests against Blender in ``--background`` mode.
    """

    _background = True
    _port = _PORT_BACKGROUND


@unittest.skipUnless(
    os.environ.get("BLENDER_BIN") and os.environ.get("BLENDER_MCP"),
    "BLENDER_BIN and BLENDER_MCP environment variables must be set",
)
class TestForegroundServer(_TestServerMixin, unittest.TestCase):
    """
    Run all tests against Blender without ``--background`` (full GUI).
    """

    _background = False
    _port = _PORT_FOREGROUND


@unittest.skipUnless(
    os.environ.get("BLENDER_BIN") and os.environ.get("BLENDER_MCP"),
    "BLENDER_BIN and BLENDER_MCP environment variables must be set",
)
class TestInteractiveServer(_TestServerMixin, unittest.TestCase):
    """
    Run all tests against Blender in interactive mode (timer-based polling).
    """

    _background = False
    _interactive = True
    _port = _PORT_INTERACTIVE


if __name__ == "__main__":
    unittest.main()
