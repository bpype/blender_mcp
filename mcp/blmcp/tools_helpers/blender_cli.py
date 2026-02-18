# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Run toolcode via ``blender --background``.
"""

__all__ = (
    "run_blender_cli",
    "synced_blend_for_cli",
)

import contextlib
import json
import logging
import os
import subprocess
from collections.abc import Generator
from typing import cast

from blmcp.tools_helpers.connection import send_code

_log = logging.getLogger(__name__)

_RESULT_PREFIX = "__BLMCP_RESULT__"
_ERROR_PREFIX = "__BLMCP_ERROR__"
_CLI_TIMEOUT = 120.0
_MAX_NUMBERED_PATHS = 10000


def _get_blender_path() -> str:
    return os.environ.get("BLENDER_PATH", "blender")


def run_blender_cli(
    blend_file: str,
    code: str,
    timeout: float = _CLI_TIMEOUT,
) -> dict[str, object]:
    """
    Run Python code inside ``blender --background``.

    *blend_file* is the path to the ``.blend`` file to open.
    *code* is executed via ``exec()`` and should assign to ``result``.

    Returns the JSON-deserialised ``result`` value.
    """
    blender = _get_blender_path()

    wrapper = (
        "import json\n"
        "try:\n"
        "    _ns = {{}}\n"
        "    exec({!r}, _ns)\n"
        '    print("{:s}" + json.dumps(_ns.get("result")))\n'
        "except Exception as ex:\n"
        '    print("{:s}" + json.dumps(str(ex)))\n'
    ).format(code, _RESULT_PREFIX, _ERROR_PREFIX)

    try:
        proc = subprocess.run(
            [blender, "--background", blend_file, "--python-expr", wrapper],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as ex:
        raise RuntimeError("Blender CLI timed out after {:.0f}s".format(timeout)) from ex
    except FileNotFoundError as ex:
        raise RuntimeError(
            "Blender executable not found at '{:s}'. "
            "Set the BLENDER_PATH environment variable to the correct path.".format(blender)
        ) from ex

    for line in proc.stdout.splitlines():
        if line.startswith(_RESULT_PREFIX):
            return cast(dict[str, object], json.loads(line[len(_RESULT_PREFIX):]))
        if line.startswith(_ERROR_PREFIX):
            raise RuntimeError("Blender error: {:s}".format(json.loads(line[len(_ERROR_PREFIX):])))

    raise RuntimeError(
        "No result marker in Blender output.\nstdout: {:s}\nstderr: {:s}".format(proc.stdout, proc.stderr)
    )


def _numbered_blend_path(filepath: str) -> str:
    """
    Return an unused path like ``/path/to/file_mcp_0001.blend``.
    """
    base, ext = os.path.splitext(filepath)
    for i in range(1, _MAX_NUMBERED_PATHS):
        candidate = "{:s}_mcp_{:04d}{:s}".format(base, i, ext)
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("Could not find an unused numbered path for '{:s}'".format(filepath))


@contextlib.contextmanager
def synced_blend_for_cli(blend_file: str) -> Generator[str, None, None]:
    """
    Context manager that ensures *blend_file* reflects unsaved changes.

    When a running Blender instance has the same file open with unsaved
    modifications, a numbered copy is saved and yielded. The copy is
    deleted on exit. When no instance is reachable or the file is clean,
    *blend_file* is yielded unchanged.
    """
    temp_path: str | None = None
    try:
        try:
            response = send_code(
                "import bpy, os\n"
                "result = {\"is_dirty\": bpy.data.is_dirty, \"filepath\": bpy.data.filepath}\n"
            )
        except ConnectionError:
            # No running Blender instance, use the on-disk file as-is.
            yield blend_file
            return

        is_dirty = response.get("is_dirty", False)
        blender_filepath = str(response.get("filepath", ""))

        # Compare normalised paths to see if this is the same file.
        if (
            not blender_filepath
            or os.path.realpath(blend_file) != os.path.realpath(blender_filepath)
        ):
            yield blend_file
            return

        if not is_dirty:
            yield blend_file
            return

        # Dirty file, save a numbered copy.
        temp_path = _numbered_blend_path(blend_file)
        send_code(
            "import bpy\n"
            "bpy.ops.wm.save_as_mainfile(filepath={!r}, copy=True)\n".format(temp_path)
        )
        yield temp_path
    finally:
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except OSError as ex:
                _log.warning("Failed to remove temporary file '{:s}': {:s}".format(temp_path, str(ex)))
