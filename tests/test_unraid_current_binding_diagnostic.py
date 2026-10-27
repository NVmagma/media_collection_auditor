import json
from scripts.unraid_current_binding_diagnostic import check_values


def test_formatting_only_settings_change_is_distinguished_without_exposing_values():
    values = dict(binding={'source_revision':'a'*40, 'policy_sha256':'policy', 'saved_config_sha256':'old-bytes'},
        revision='a'*40, policy_hash='policy', config_hash='new-bytes',
        config={'JELLYFIN_API_TOKEN':'private-token'}, prepared_config={'JELLYFIN_API_TOKEN':'private-token'})
    result = check_values(**values)
    assert result['policy_hash_matches'] is True and result['saved_config_hash_matches'] is False
    assert result['saved_settings_semantically_match_prepared'] is True
    assert result['changed_known_setting_keys'] == []
    assert 'private-token' not in json.dumps(result)


def test_changed_setting_names_are_allowlisted_and_values_remain_private():
    result = check_values(binding={}, revision='a'*40, policy_hash='policy', config_hash='config',
        config={'ENABLE_TV':'true', 'private-extension-name':'private-value'},
        prepared_config={'ENABLE_TV':'false'})
    assert result['changed_known_setting_keys'] == ['ENABLE_TV']
    assert result['saved_settings_semantically_match_prepared'] is False
    assert 'private-extension-name' not in json.dumps(result) and 'private-value' not in json.dumps(result)
