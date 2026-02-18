# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared helpers for tool modules.
"""

__all__ = (
    "toolcode_format_call",
    "toolcode_load_from_filepath",
    "toolcode_wrap_with_calling_convention",
)

from pathlib import Path

_PARAMS_PLACEHOLDER = "__BLMCP_PARAMS__"


def toolcode_format_call(toolcode_template: str, params: object) -> str:
    """
    Substitute the parameter placeholder in *toolcode_template* with *params*.
    """
    return toolcode_template.replace(_PARAMS_PLACEHOLDER, repr(params))


def toolcode_load_from_filepath(filepath: str) -> str:
    """
    Read the ``*_toolcode.py`` file that corresponds to *filepath*.

    Given ``/path/to/tools/my_tool.py``, returns the contents of
    ``/path/to/tools/my_tool_toolcode.py``.
    """
    p = Path(filepath)
    return p.with_name(p.stem + "_toolcode.py").read_text(encoding="utf-8")


def toolcode_wrap_with_calling_convention(
    toolcode: str,
    use_result: bool = True,
) -> str:
    """
    Append the calling convention footer to *toolcode*.

    The footer inserts a placeholder that is later replaced by
    ``toolcode_format_call`` with the ``repr`` of the ``Params``
    named-tuple (or ``None`` for parameter-less tools).
    When *use_result* is True the return value is converted via ``._asdict()``.
    """
    call = "main({:s})".format(_PARAMS_PLACEHOLDER)

    if use_result:
        call += "._asdict()"

    return toolcode + "\nresult = {:s}\n".format(call)
