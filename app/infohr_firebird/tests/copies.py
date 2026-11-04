"""Deletion of Firebird test database copies, shared by every test fixture that makes one.

A copy of the 367 MB template that cannot be deleted is reported with a UserWarning, so it shows in
pytest's summary instead of silently filling the disk.
"""

import time
import warnings
from pathlib import Path


def remove_copy(path: Path) -> None:
    """Delete a database copy. Windows can hold the file for a moment after the last close, so retry.

    If it is still locked after the retries, a UserWarning names the file so the leftover copy is
    visible in the test summary and can be removed by hand.
    """
    for _ in range(20):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.25)
    warnings.warn(f"could not delete test database copy: {path}", UserWarning, stacklevel=2)
