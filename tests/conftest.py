from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def no_foreign_discovery_flows():
    """Herstellerkennung 0xFFFF passt auch auf Core-Integrationen (z. B. Kegtron).

    Deren automatisch gestartete Discovery-Flows haben in diesen Tests nichts zu suchen.
    """
    with patch("homeassistant.components.bluetooth.manager.discovery_flow.async_create_flow"):
        yield
