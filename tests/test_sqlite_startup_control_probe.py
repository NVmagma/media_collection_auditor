import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('startup_probe', Path(__file__).parents[1] / 'scripts/sqlite_startup_control_probe.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_selected_settings_never_execute_or_disclose_other_values(tmp_path):
    config = tmp_path / 'boot/config'
    config.mkdir(parents=True)
    marker = tmp_path / 'executed'
    (config / 'docker.cfg').write_text(f'DOCKER_ENABLED="yes"\nSECRET=hidden\ntouch {marker}\n')
    (config / 'go').write_text(f'touch {marker}\n')
    auto = tmp_path / 'var/lib/docker'
    auto.mkdir(parents=True)
    (auto / 'unraid-autostart').write_text('radarr 10\nhomepage\n')
    result = module.observe(tmp_path)
    assert result['settings']['/boot/config/docker.cfg'] == {'DOCKER_ENABLED': 'yes'}
    assert result['unraid_autostart']['entries'] == [
        {'container': 'radarr', 'delay_seconds': 10}, {'container': 'homepage', 'delay_seconds': None}]
    assert 'hidden' not in str(result)
    assert not marker.exists()
    assert result['production_authorized'] is False
    assert result['restart_inhibition_verified'] is False


def test_malformed_or_duplicate_settings_and_autostart_fail_closed(tmp_path):
    assert module.preference(b'DOCKER_ENABLED="yes"\nDOCKER_ENABLED="no"', 'DOCKER_ENABLED') == 'unverified'
    assert module.preference(b'DOCKER_ENABLED="$(command)"', 'DOCKER_ENABLED') == 'unverified'
    auto = tmp_path / 'var/lib/docker'
    auto.mkdir(parents=True)
    (auto / 'unraid-autostart').write_text('radarr 10\nsecret=$(command)\n')
    assert module.observe(tmp_path)['unraid_autostart'] == {'status': 'unverified', 'entries': []}
