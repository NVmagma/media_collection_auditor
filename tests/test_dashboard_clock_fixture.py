import pytest
from scripts.dashboard_clock_fixture import actual_image_acceptance


def test_dashboard_fixture_requires_actual_packaged_preview_before_writes():
    with pytest.raises(RuntimeError,match='Actual immutable preview image'):
        actual_image_acceptance()
