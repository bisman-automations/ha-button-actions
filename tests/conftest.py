"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    return


@pytest.fixture(autouse=True)
def isolated_config_dir(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Give every Home Assistant test its own config directory.

    pytest-homeassistant-custom-component points ``hass.config.config_dir`` at
    one ``testing_config`` folder inside the installed package, shared by every
    test and every pytest-xdist worker. The blueprint import tests write
    ``automations.yaml`` there, so under ``pytest -n`` one worker's file
    replaced another's between writing and reading it: the automation wasn't
    found, the import step showed its form again with ``not_blueprint``, and
    the test failed (it also left the file behind for later runs). A fresh
    ``tmp_path`` per test keeps each test's files its own.

    Tests that don't use ``hass`` (the pure gesture tests) are left alone, so
    they don't start a Home Assistant instance for nothing.
    """
    if "hass" not in request.fixturenames:
        return
    hass = request.getfixturevalue("hass")
    hass.config.config_dir = str(tmp_path)
