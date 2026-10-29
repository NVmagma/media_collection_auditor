"""Fixed read-only shared/native comparison; stdout contains no media names."""
import json
from app.sqlite_media_view_review import compare_media_views


def main():
    report=compare_media_views(shared='/shared',native='/native')
    print(json.dumps(report,sort_keys=True))
    return 0 if report['status']=='media_views_observed' and report['all_stage_metadata_matches'] else 2

if __name__=='__main__':raise SystemExit(main())
