import pytest
from app.sqlite_nfs_config_candidate import disabled_nfs_candidate, reviewed_restore_candidate


@pytest.mark.parametrize('line',[b'shareNFSEnabled=yes',b'shareNFSEnabled="yes"',b'shareNFSEnabled=no',b'shareNFSEnabled="no"'])
@pytest.mark.parametrize('ending',[b'',b'\n',b'\r\n'])
def test_only_explicit_preference_changes(line,ending):
    before=b'# comment\nother="unchanged"\n'+line+ending
    expected=before.replace(b'=yes',b'=no').replace(b'="yes"',b'="no"')
    assert disabled_nfs_candidate(before)==expected
    assert reviewed_restore_candidate(original=before,disabled=expected,current=expected)==before


@pytest.mark.parametrize('content',[b'',b'other=yes\n',b'shareNFSEnabled=yes\nshareNFSEnabled=no\n',
    b'shareNFSEnabled=$(command)\n',b'export shareNFSEnabled=yes\n',b' shareNFSEnabled=yes\n',
    b'shareNFSEnabled="yes" # comment\n',b'shareNFSEnabled=maybe\n',b'shareNFSEnabled=yes\0'])
def test_ambiguous_missing_or_noncanonical_preference_blocks(content):
    with pytest.raises((ValueError,UnicodeError)):disabled_nfs_candidate(content)


def test_intervening_unrelated_edit_blocks_restore():
    before=b'shareNFSEnabled=yes\nother=original\n'
    disabled=disabled_nfs_candidate(before)
    with pytest.raises(RuntimeError,match='refuse restoration'):
        reviewed_restore_candidate(original=before,disabled=disabled,current=disabled.replace(b'original',b'changed'))


def test_substituted_disabled_candidate_blocks_restore():
    with pytest.raises(RuntimeError):
        reviewed_restore_candidate(original=b'shareNFSEnabled=yes\n',disabled=b'other=no\n',current=b'other=no\n')
