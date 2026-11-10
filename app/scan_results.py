"""Browse saved title decisions without changing them or exposing private fields."""
from app.scan_details import project_details, OUTCOMES


def recorded_details(record):
    """Do not turn a proposal or summary count into a completed action."""
    pages = record.get('title_detail_pages')
    if pages is None:
        detail = project_details(record.get('title_details'))
        return (detail['items'], detail['truncated']) if detail else ([], True)
    if not isinstance(pages, list) or len(pages) > 1000:
        raise ValueError('Recorded details unavailable')
    rows = []
    total = None
    for index, page in enumerate(pages):
        detail = project_details(page)
        if detail is None or (total is not None and detail['total_records'] != total):
            raise ValueError('Recorded details unavailable')
        total = detail['total_records']
        if index < len(pages)-1 and len(detail['items']) != 100:
            raise ValueError('Recorded details unavailable')
        rows.extend(detail['items'])
    if total is not None and total != len(rows):
        raise ValueError('Recorded details unavailable')
    return rows, False


def browse(record, *, query='', library='all', outcome='all', page=1):
    if (not isinstance(query,str) or len(query)>255 or library not in ('all','Movies','TV')
            or outcome not in ('all',*OUTCOMES) or type(page) is not int or not 1<=page<=4000):
        raise ValueError('Invalid result filters')
    rows, partial = recorded_details(record)
    matching = [row for row in rows if (library=='all' or row['library']==library)
                and (outcome=='all' or row['outcome']==outcome)
                and query.casefold() in row['title'].casefold()]
    pages = max(1,(len(matching)+24)//25)
    page = min(page,pages)
    return dict(items=matching[(page-1)*25:page*25],total=len(rows),matched=len(matching),
                partial=partial,page=page,pages=pages,query=query,library=library,outcome=outcome)
