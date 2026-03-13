# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

__all__ = ()

import contextlib
from typing import Generator


@contextlib.contextmanager
def _backup_attrs(obj: object, *names: str) -> Generator[dict[str, object], None, None]:
    """
    Context manager that saves named attributes on entry and restores them on exit.
    """
    saved = {name: getattr(obj, name) for name in names}
    try:
        yield saved
    finally:
        for name, value in saved.items():
            setattr(obj, name, value)
