import pytest

from app.sqlite_boot_share_config_candidate import (
    disabled_boot_share_candidate,reviewed_boot_share_restore_candidate,
    prepare_disposable_boot_share_config_plan,
)
from app.sqlite_disposable_nfs_config_plan import MARKER


BASE=(b'shareSMBEnabled="yes"\r\nshareNFSEnabled=yes\r\n'
      b'shareMoverSchedule="0 3 * * *"\r\nstartArray="yes"\r\n'
      b'other="preserve exactly"\r\n')


def test_share_opt_out_preserves_autostart_and_unrelated_bytes():
    expected=BASE.replace(b'shareSMBEnabled="yes"',b'shareSMBEnabled="no"').replace(
        b'shareNFSEnabled=yes',b'shareNFSEnabled=no').replace(
        b'shareMoverSchedule="0 3 * * *"',b'shareMoverSchedule=""')
    candidate=disabled_boot_share_candidate(BASE)
    assert candidate==expected
    assert disabled_boot_share_candidate(candidate)==candidate
    assert reviewed_boot_share_restore_candidate(original=BASE,disabled=candidate,current=candidate)==BASE
    with pytest.raises(RuntimeError,match='Configuration changed'):
        reviewed_boot_share_restore_candidate(original=BASE,disabled=candidate,current=candidate+b'# edit\n')


@pytest.mark.parametrize('line',[
    b'shareMoverSchedule=""',b'shareMoverSchedule=',
    b'shareMoverSchedule="0 */2 * * 0,6"',
])
def test_explicit_disabled_or_simple_cron_review_formats(line):
    content=BASE.replace(b'shareMoverSchedule="0 3 * * *"',line)
    result=disabled_boot_share_candidate(content)
    assert b'shareMoverSchedule=""' in result or b'shareMoverSchedule=\r\n' in result


@pytest.mark.parametrize('line',[
    b'export shareMoverSchedule="0 3 * * *"',b'shareMoverSchedule ="0 3 * * *"',
    b'shareMoverSchedule="$(touch /tmp/unsafe)"',b'shareMoverSchedule="@daily"',
    b'shareMoverSchedule="0 3 * * *"; command',
    b'shareMoverSchedule="0 3 * * *"\r\nshareMoverSchedule=""',
    b'# missing shareMoverSchedule',
    b'shareMoverSchedule="99 3 * * *"',b'shareMoverSchedule="0 */0 * * *"',
    b'shareMoverSchedule="0 3 31-1 * *"',b'shareMoverSchedule="0 3 * 13 *"',
    b'shareMoverSchedule="0, 3 * * *"',
])
def test_ambiguous_schedule_never_produces_boot_candidate(line):
    with pytest.raises(ValueError):
        disabled_boot_share_candidate(BASE.replace(b'shareMoverSchedule="0 3 * * *"',line))


def test_marked_plan_retains_source_and_does_not_change_disk_config(tmp_path):
    root=tmp_path.resolve()
    (root/'.disposable_host_config').write_bytes(MARKER)
    (root/'share.cfg').write_bytes(BASE)
    (root/'disk.cfg').write_bytes(b'startArray="yes"\n')
    result=prepare_disposable_boot_share_config_plan(root)
    assert result['apply_authorized'] is False and result['production_authorized'] is False
    assert (root/'share.cfg').read_bytes()==BASE
    assert (root/'disk.cfg').read_bytes()==b'startArray="yes"\n'
    assert (root/'boot-share-plan/before.cfg').read_bytes()==BASE
    assert (root/'boot-share-plan/disabled-candidate.cfg').read_bytes()==disabled_boot_share_candidate(BASE)
    with pytest.raises(FileExistsError):prepare_disposable_boot_share_config_plan(root)


def test_unmarked_root_cannot_prepare_boot_plan(tmp_path):
    (tmp_path/'share.cfg').write_bytes(BASE)
    with pytest.raises(FileNotFoundError):prepare_disposable_boot_share_config_plan(tmp_path.resolve())
    assert not (tmp_path/'boot-share-plan').exists()
