"""Advisory comparison of local title directories with one Arr catalog."""

from collections import Counter
import unicodedata

from app.title_identity import validate_title_folder


LABELS = {
    'exact': 'Exact Arr path',
    'different': 'Similar folder name at a different path',
    'ambiguous': 'Multiple matching Arr records',
    'unmatched': 'No matching Arr folder name',
}


def _fold(name):
    return unicodedata.normalize('NFC', name).casefold()


def compare_folders(stages, remote_roots, catalog):
    by_name = Counter()
    by_path = Counter()
    for name, paths in catalog.items():
        by_name[_fold(name)] += len(paths)
        by_path.update(paths)

    rows = []
    for stage, folders in stages.items():
        for folder in folders:
            title = validate_title_folder(folder['title'])
            matches = by_name[_fold(title)]
            exact_matches = by_path[remote_roots[stage] + '/' + title]
            if exact_matches == 1:
                status = 'exact'
            elif exact_matches > 1 or matches > 1:
                status = 'ambiguous'
            elif matches:
                status = 'different'
            else:
                status = 'unmatched'
            rows.append({'title': title, 'stage': stage, 'status': status})

    rows.sort(key=lambda row: (row['title'].casefold(), row['stage']))
    return rows, Counter(row['status'] for row in rows)
