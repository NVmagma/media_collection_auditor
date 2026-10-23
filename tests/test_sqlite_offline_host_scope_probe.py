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
