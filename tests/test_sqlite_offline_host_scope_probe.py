import os
from pathlib import Path
import subprocess


SCRIPT=Path(__file__).resolve().parents[1]/'scripts/sqlite_offline_host_scope_probe.sh'


def test_selected_settings_and_redacted_cron_never_execute_content(tmp_path):
    root=tmp_path.resolve()/'host';root.mkdir()
    (root/'boot/config').mkdir(parents=True)
    (root/'boot/config/share.cfg').write_text('shareSMBEnabled="yes"\nshareNFSEnabled="no"\nAPI_SECRET=must_not_print\n')
    (root/'etc/cron.d').mkdir(parents=True)
    sentinel=tmp_path/'executed'
    (root/'etc/cron.d/root').write_text(
        '# mover comment\n0 3 * * * /usr/local/sbin/mover --token must_not_print\n'
        +f'* * * * * touch {sentinel}\n')
    # Mac lacks GNU timeout; fixtures are bounded and this shim only runs readers.
    tools=tmp_path/'bin';tools.mkdir()
    timeout=tools/'timeout';timeout.write_text('#!/bin/sh\nshift\nexec "$@"\n');timeout.chmod(0o700)
    realpath=tools/'realpath'
    realpath.write_text('#!/bin/sh\nfor value do :; done; printf "%s\\n" "$value"\n')
    realpath.chmod(0o700)
    result=subprocess.run(['/bin/bash',str(SCRIPT),str(root)],capture_output=True,text=True,
                          env={**os.environ,'PATH':str(tools)+os.pathsep+os.defpath})
    assert result.returncode==0,result.stderr
    assert 'key=shareSMBEnabled observed=yes' in result.stdout
    assert 'key=shareNFSEnabled observed=no' in result.stdout
    assert 'active_entries=2 mover_mentions=1' in result.stdout
    assert 'must_not_print' not in result.stdout
    assert not sentinel.exists()
    assert 'writer_exclusion_verified=false' in result.stdout
    assert 'not_collected_for_fixture' in result.stdout


def run_preference_fixture(tmp_path,content):
    root=tmp_path.resolve()/'host';root.mkdir()
    (root/'boot/config').mkdir(parents=True)
    (root/'boot/config/share.cfg').write_bytes(content)
    tools=tmp_path/'tools';tools.mkdir()
    for name,body in {
        'timeout':'shift\nexec "$@"',
        'realpath':'for value do :; done; printf "%s\\n" "$value"',
    }.items():
        path=tools/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o700)
    result=subprocess.run(['/bin/bash',str(SCRIPT),str(root)],capture_output=True,text=True,
        env={**os.environ,'PATH':str(tools)+os.pathsep+os.defpath})
    assert result.returncode==0,result.stderr
    return result.stdout


def test_crlf_preferences_are_observed_without_modifying_source(tmp_path):
    before=b'shareSMBEnabled="yes"\r\nshareNFSEnabled="no"\r\n'
    output=run_preference_fixture(tmp_path,before)
    assert 'key=shareSMBEnabled observed=yes assignments=1 terminal_cr_lines=2' in output
    assert 'key=shareNFSEnabled observed=no assignments=1 terminal_cr_lines=2' in output
    assert (tmp_path/'host/boot/config/share.cfg').read_bytes()==before


def test_unquoted_canonical_values_are_observed(tmp_path):
    output=run_preference_fixture(tmp_path,b'shareSMBEnabled=yes\nshareNFSEnabled=no\n')
    assert 'key=shareSMBEnabled observed=yes assignments=1' in output
    assert 'key=shareNFSEnabled observed=no assignments=1' in output


def test_duplicate_and_executable_looking_values_stay_unverified(tmp_path):
    output=run_preference_fixture(tmp_path,
        b'shareSMBEnabled="yes"\nshareSMBEnabled="no"\nshareNFSEnabled=$(must_not_execute)\n')
    assert 'key=shareSMBEnabled observed=unverified assignments=2' in output
    assert 'key=shareNFSEnabled observed=unverified assignments=1' in output
    assert 'must_not_execute' not in output
