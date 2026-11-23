from pathlib import Path

import pytest
from django.conf import settings

# pytest must not import a welcome test module when the app is not installed: importing welcome.models with the flag
# off raises at collection.
_WELCOME_INSTALLED = "welcome" in settings.INSTALLED_APPS


def pytest_ignore_collect(collection_path: Path, config: object) -> bool | None:
    if not _WELCOME_INSTALLED and collection_path.name.startswith("test_") and collection_path.suffix == ".py":
        return True
    return None


def pytest_make_collect_report(collector: pytest.Collector) -> pytest.CollectReport | None:
    # pytest exempts files named on the command line from pytest_ignore_collect, so the import is refused here too.
    if not _WELCOME_INSTALLED and isinstance(collector, pytest.Module):
        longrepr = (str(collector.path), 0, "welcome app not installed (PUBLIC_WELCOME is off)")
        return pytest.CollectReport(collector.nodeid, "skipped", longrepr, None)
    return None
