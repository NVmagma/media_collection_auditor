import json

import pytest

from scripts import sqlite_preview_cutover_fixture as fixtures
from scripts.sqlite_preview_fresh import settings_from_packet
from scripts.sqlite_preview_release_request import fingerprint


@pytest.fixture
def packet():
    case = fixtures.PreviewCutoverFixtureTests(); case.setUp(); case.inputs()
    (case.root/'original-template.xml').write_text('<Container><Name>media_collection_auditor</Name></Container>')
    report = case.write()
    try: yield case,report
    finally: case.doCleanups()


def read(case,report,selected=None):
    info=case.root.stat()
    return settings_from_packet(case.root,(info.st_dev,info.st_ino),selected or fingerprint(report))


def test_verified_settings_reused_without_importing_or_modifying_old_tracking(packet):
    case,report=packet
    before={p.name:p.read_bytes() for p in case.root.iterdir()}
    _,_,env,proposed,_=read(case,report)
    assert env['INTEGRATION_API_TOKEN']==fixtures.SECRET
    assert env['AUDITOR_STATE_BACKEND']=='sqlite' and proposed['DRY_RUN']=='true'
    assert {p.name:p.read_bytes() for p in case.root.iterdir()}==before


def test_wrong_selection_cannot_supply_fresh_settings(packet):
    case,report=packet
    with pytest.raises(RuntimeError): read(case,report,'0'*64)


@pytest.mark.parametrize('name', ['original-config.json','preview.env','proposed-config.json'])
def test_changed_old_packet_settings_are_refused(packet,name):
    case,report=packet
    path=case.root/name
    path.write_bytes(path.read_bytes()+b'\nchanged')
    with pytest.raises((RuntimeError,ValueError)): read(case,report)
