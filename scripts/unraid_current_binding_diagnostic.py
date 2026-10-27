"""Read-only current-preview diagnostics; output booleans/fixed codes, no secrets."""
import hashlib
import json
import os
from pathlib import Path
import sys


def _read(path):
    from app.sqlite_scheduled_paths import _open_directory
    from app.sqlite_release_recovery import _local
    parent = _open_directory(str(path.parent))
    try:
        return _local(parent, path.name)
    finally:
        os.close(parent)


def check_values(*, binding, revision, policy_hash, config_hash, config, prepared_config):
    from app.config_store import KEYS
    result = {'source_revision_matches': binding.get('source_revision') == revision,
              'policy_hash_matches': None if policy_hash is None else binding.get('policy_sha256') == policy_hash,
              'saved_config_hash_matches': binding.get('saved_config_sha256') == config_hash}
    if isinstance(config, dict) and isinstance(prepared_config, dict):
        result['saved_settings_semantically_match_prepared'] = config == prepared_config
        result['changed_known_setting_keys'] = sorted(key for key in KEYS
            if config.get(key) != prepared_config.get(key))
    return result


def diagnose(container):
    from app.sqlite_json import parse_unique_json
    from app.sqlite_preview_activation import _effective, _policy, _revision, _roots, BINDING, validate_preview_activation
    from app.sqlite_release_recovery import _encode
    from app.state_store import GuardedSQLiteStateStore
    from app.sqlite_operation_coordinator import INTENTS_KEY
    result = {'status': 'current_binding_review_required', 'read_only': True,
              'automatic_action': 'none', 'service_changes_performed': False,
              'media_actions_authorized': False, 'binding_modified': False}
    stage = 'container_environment'
    try:
        if container.get('Name') != '/media_collection_auditor':
            raise ValueError('known_service_required')
        settings = dict(item.split('=',1) for item in container['Config']['Env'])
        stage = 'effective_saved_settings'
        values, config_hash = _effective(settings)
        database = Path(values['SQLITE_STATE_FILE'])
        if not database.is_absolute(): raise ValueError('absolute_database_required')
        stage = 'binding_records'
        binding = parse_unique_json(_read(database.parent/BINDING)[0])
        saved = parse_unique_json(_read(Path(values['WEB_CONFIG_FILE']))[0])
        try:
            prepared = parse_unique_json(_read(database.parent.parent/'preview-config.json')[0])
        except (OSError, ValueError):
            prepared = None
        result.update(check_values(binding=binding, revision=_revision(), policy_hash=None,
            config_hash=config_hash, config=saved, prepared_config=prepared))
        stage = 'preview_policy'
        config, source, database, policy_hash = _policy(values)
        result['policy_hash_matches'] = binding.get('policy_sha256') == policy_hash
        stage = 'path_identities'
        control_info = database.parent.stat(); database_info = database.stat(follow_symlinks=False)
        result['control_identity_matches'] = binding.get('control_identity') == [control_info.st_dev, control_info.st_ino]
        result['database_identity_matches'] = binding.get('database_identity') == [database_info.st_dev, database_info.st_ino]
        result['media_root_identities_match'] = binding.get('media_roots') == _roots(config, (control_info.st_dev,control_info.st_ino))
        stage = 'tracking_snapshot'
        state, revision = GuardedSQLiteStateStore(database).load_with_revision()
        result['snapshot_revision_matches'] = type(revision) is int and revision == binding.get('snapshot_revision') == 0
        result['snapshot_hash_matches'] = binding.get('snapshot_sha256') == hashlib.sha256(_encode(state)).hexdigest()
        result['pending_operation_present'] = INTENTS_KEY in state
        stage = 'retained_source'
        original, source_info = _read(source)
        from app.sqlite_release_preparation import REQUEST, COMPLETE, BACKUP, _identity
        request_raw = _read(database.parent/REQUEST)[0]
        receipt_raw = _read(database.parent/COMPLETE)[0]
        backup_raw = _read(database.parent/BACKUP)[0]
        request = parse_unique_json(request_raw); receipt = parse_unique_json(receipt_raw)
        result['retained_source_matches_backup'] = original == backup_raw
        result['retained_source_identity_matches'] = request.get('source_identity') == list(_identity(source_info))
        result['preparation_database_identity_matches'] = receipt.get('database_identity') == [database_info.st_dev,database_info.st_ino]
        expected = binding.get('prepared_inputs') or {}
        for name, raw, label in ((REQUEST,request_raw,'preparation_request_hash_matches'),
                                  (COMPLETE,receipt_raw,'preparation_receipt_hash_matches'),
                                  (BACKUP,backup_raw,'retained_backup_hash_matches')):
            result[label] = expected.get(name) == hashlib.sha256(raw).hexdigest()
        stage = 'full_packaged_validation'
        validate_preview_activation(settings=settings)
        result['status'] = 'current_binding_valid'
    except Exception as error:
        result['diagnostic_stage'] = stage
        result['error_type'] = type(error).__name__
    return result


def main():
    try:
        from app.sqlite_json import parse_unique_json
        raw = sys.stdin.buffer.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024: raise ValueError('bounded_input_required')
        payload = parse_unique_json(raw)
        if len(payload['containers']) != 1: raise ValueError('one_container_required')
        result = diagnose(payload['containers'][0])
    except Exception as error:
        result = {'status': 'current_binding_review_required', 'read_only': True, 'automatic_action': 'none',
                  'binding_modified': False, 'diagnostic_stage': 'inspect_input', 'error_type': type(error).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'current_binding_valid' else 2


if __name__ == '__main__':
    raise SystemExit(main())
