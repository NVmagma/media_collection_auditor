"""Read-only dashboard filesystem inventory tests."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import web


class DashboardInventoryTests(unittest.TestCase):
    def test_real_directories_determine_stage_counts(self):
        with tempfile.TemporaryDirectory() as root:
            for folder in ("Movies", "Movies_hold", "Movies_keep", "Movies_removal"):
                os.mkdir(os.path.join(root, folder))
            os.mkdir(os.path.join(root, "Movies_keep", "Kept"))
            os.mkdir(os.path.join(root, "Movies", "New"))
            state = {"first_seen": {"Stale": "2020-01-01T00:00:00"},
                     "keep_seen": {"Kept": "2026-01-01T00:00:00"}}
            with patch.dict(os.environ, {"MEDIA_PATH": root}, clear=False):
                stages, warnings = web.filesystem_stages(state, {
                    "MEDIA_PATH": root, "ENABLE_MOVIES": "true", "ENABLE_TV": "false"})
        self.assertFalse(warnings)
        self.assertEqual([item["title"] for item in stages["Waiting"]], ["New"])
        self.assertEqual([item["title"] for item in stages["Keep"]], ["Kept"])
        self.assertIsNone(stages["Waiting"][0]["since"])

    def test_collection_health_reports_missing_stale_and_pending(self):
        state = {"first_seen": {"Stale": "2020-01-01T00:00:00"},
                 "arr_sync_pending": {"Kept": {"stage": "keep", "root": "/media/Movies_keep"}}}
        stages = {"Waiting": [{"library": "Movies", "title": "New", "since": None}],
                  "Holding": [], "Removal": [], "Keep": []}
        issues = web.collection_health(state, stages, [])
        details = [item["detail"] for item in issues]
        self.assertTrue(any("no tracking timestamp" in detail for detail in details))
        self.assertTrue(any("no matching folder" in detail for detail in details))
        self.assertTrue(any("sync pending" in detail for detail in details))

    def test_collection_health_does_not_claim_missing_media_when_mount_unavailable(self):
        state = {"in_removal": {"Important": "2020-01-01T00:00:00"}}
        stages = {"Waiting": [], "Holding": [], "Removal": [], "Keep": []}
        issues = web.collection_health(state, stages, ["Movies Removal: directory unavailable (/media/Movies_removal)"])
        self.assertEqual(issues, [])

    def test_unavailable_mount_reports_warning(self):
        with tempfile.TemporaryDirectory() as root:
            stages, warnings = web.filesystem_stages({}, {
                "MEDIA_PATH": root, "ENABLE_MOVIES": "true", "ENABLE_TV": "false"})
        self.assertEqual(sum(map(len, stages.values())), 0)
        self.assertEqual(len(warnings), 4)


if __name__ == "__main__":
    unittest.main()


def test_tmm_trash_is_not_a_title_in_either_library(tmp_path):
    for library in ('Movies','TV'):
        for suffix in ('','_hold','_keep','_removal'):
            root = tmp_path/(library+suffix); root.mkdir()
            trash = root/'.deletedByTMM'; trash.mkdir()
            (trash/'deleted-episode.mkv').write_bytes(b'retained trash, not an active title')
        show = tmp_path/library/'Real title'; show.mkdir()
        (show/'video.mkv').write_bytes(b'video')
    stages, warnings = web.filesystem_stages({},dict(MEDIA_PATH=str(tmp_path), ENABLE_MOVIES='true',ENABLE_TV='true'))
    assert not warnings
    assert [(row['library'],row['title']) for row in stages['Waiting']] == [('Movies','Real title'),('TV','Real title')]
    assert all(row['title'] != '.deletedByTMM' for rows in stages.values() for row in rows)
    assert (tmp_path/'TV'/'.deletedByTMM'/'deleted-episode.mkv').exists()


def test_metadata_only_library_filter_keeps_unknown_and_unreadable_folders(monkeypatch):
    from copy import deepcopy
    import app.orphan_inventory
    items = [{'title':title,'library':'TV','since':None} for title in ('Empty','Metadata','Video','Unknown','Unreadable')]
    stages = dict(Waiting=items,Holding=[],Keep=[],Removal=[])
    before = deepcopy(stages)
    def inspect(path):
        title = Path(path).name
        if title == 'Unreadable': raise OSError('cannot read')
        return {'status':{'Empty':'metadata_only','Metadata':'metadata_only','Video':'video_present','Unknown':'unknown_files'}[title]}
    monkeypatch.setattr(app.orphan_inventory,'inspect_title',inspect)
    visible, hidden = web.visible_library_stages(stages, {'MEDIA_PATH':'/media'})
    assert hidden == 2
    assert [row['title'] for row in visible['Waiting']] == ['Video','Unknown','Unreadable']
    assert stages == before


def test_housekeeping_type_must_match():
    import stat
    from app.stage_entries import is_housekeeping
    assert is_housekeeping('.deletedByTMM',stat.S_IFDIR)
    assert is_housekeeping('.DS_Store',stat.S_IFREG)
    assert not is_housekeeping('.deletedByTMM',stat.S_IFLNK)
    assert not is_housekeeping('.DS_Store',stat.S_IFDIR)
    assert not is_housekeeping('.unknown',stat.S_IFDIR)
