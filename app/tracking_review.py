"""Compare saved clocks with folders without changing state or contacting services."""
from datetime import datetime
import unicodedata
from app.title_identity import validate_title_folder

SECTIONS={'Waiting':'first_seen','Holding':'queued','Keep':'keep_seen','Removal':'in_removal'}
LABELS={'missing_clock':'Folder without stage clock','missing_folder':'Record without exact folder',
        'other_stage':'Record / folder stage mismatch','duplicate_folder':'Folder in multiple stages',
        'clock_conflict':'Multiple saved stage clocks','near_name':'Possible name variant',
        'coverage':'Directory coverage unavailable','arr':'Last scan Arr issue','pending':'Arr sync pending'}
ARR_REASONS={'arr_record_missing':'The selected action had no matching Arr record.',
    'arr_path_conflict':'The selected action had a different Arr source path.',
    'arr_record_ambiguous':'The selected action had more than one Arr match.',
    'arr_catalog_unavailable':'The selected action could not verify the Arr catalog.'}


def _title(value):
    validate_title_folder(value)
    if len(value)>255 or any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError('Invalid title')
    return value


def _identity(key):
    if not isinstance(key,str):raise ValueError('Invalid tracking identity')
    return ('TV',_title(key[3:])) if key.startswith('TV/') else ('Movies',_title(key))


def _fold(value):
    return unicodedata.normalize('NFKC',value).casefold()


def review(state,stages,warnings,history,*,libraries,kind='all',library='all',query='',page=1):
    if (kind not in ('all',*LABELS) or library not in ('all','Movies','TV') or not isinstance(query,str)
            or len(query)>255 or type(page) is not int or not 1<=page<=100000
            or any(name not in ('Movies','TV') for name in libraries)):
        raise ValueError('Invalid tracking review filters')
    rows=[];present={};folded={};clocks={}
    def add(lib,title,stage,category,detail):
        rows.append(dict(library=lib,title=title,stage=stage,kind=category,label=LABELS[category],detail=detail))
    unavailable={(lib,stage) for lib in libraries for stage in SECTIONS
                 if any(message.startswith(lib+' '+stage+':') for message in warnings)}
    for stage,section in SECTIONS.items():
        if not isinstance(state.get(section,{}),dict):raise ValueError('Invalid tracking section')
        for key in state.get(section,{}):
            identity=_identity(key)
            if identity[0] in libraries:clocks.setdefault(identity,set()).add(stage)
        for item in stages.get(stage,[]):
            lib,title=item['library'],_title(item['title'])
            if lib not in libraries or (lib,stage) in unavailable:continue
            present.setdefault((lib,title),set()).add(stage)
            folded.setdefault((lib,_fold(title)),set()).add(title)
    for (lib,title),locations in present.items():
        saved=clocks.get((lib,title),set())
        if len(locations)>1:
            add(lib,title,', '.join(sorted(locations)),'duplicate_folder','Exact folder name observed in more than one lifecycle stage. No folder was moved.')
        for stage in sorted(locations-saved):
            add(lib,title,stage,'missing_clock','No saved date for this exact stage. '+
                ('A date exists in '+', '.join(sorted(saved))+'. ' if saved else '')+'No folder date or other-stage date has been substituted.')
    for (lib,title),saved in clocks.items():
        locations=present.get((lib,title),set())
        if len(saved)>1:add(lib,title,', '.join(sorted(saved)),'clock_conflict','More than one stage clock is recorded. All saved dates are preserved.')
        for stage in sorted(saved-locations):
            if (lib,stage) in unavailable:continue
            if locations:
                add(lib,title,stage,'other_stage','Saved '+stage+' clock; exact folder observed in '+', '.join(sorted(locations))+'. No clocks were changed.')
            elif any(name==lib for name,_ in unavailable):
                add(lib,title,stage,'coverage','Not observed in the recorded stage; another lifecycle directory is unavailable. Current location is unknown.')
            else:
                add(lib,title,stage,'missing_folder','No exact folder match in the readable lifecycle directories. This does not prove media was deleted.')
            variants=sorted(folded.get((lib,_fold(title)),set())-{title})
            if variants:
                add(lib,title,stage,'near_name','Possible case or Unicode name variant: '+', '.join(variants[:3])+('. Additional variants exist.' if len(variants)>3 else '.')+' No identity or clock was merged.')
    for lib,stage in sorted(unavailable):
        add(lib,'—',stage,'coverage','Directory is unavailable or its bounded listing was incomplete. No absence or empty-directory conclusion was made.')
    for key in state.get('arr_sync_pending',{}):
        lib,title=_identity(key)
        if lib in libraries:add(lib,title,'Not verified','pending','A saved Arr sync entry exists. Use operation recovery; another update has not been sent.')
    partial=True;latest=None
    record=next((r for r in history if isinstance(r,dict) and r.get('worker_mode')=='json_serialized'),None)
    if record is not None:
        decisions=record.get('json_decisions')
        if isinstance(decisions,list) and len(decisions)<=100000:
            total=record.get('scanned_titles')
            partial=type(total) is int and total>len(decisions)
            stamp=record.get('started_at')
            try:
                parsed=datetime.fromisoformat(stamp)
                if parsed.tzinfo is None:raise ValueError()
                latest=parsed.isoformat()
            except (ValueError,TypeError):partial=True
            for item in decisions:
                if not isinstance(item,dict):partial=True;continue
                reason=item.get('reason')
                if not isinstance(reason,str):partial=True;continue
                if reason not in ARR_REASONS:continue
                try:lib,title=_identity(item['media_key'])
                except (KeyError,ValueError,TypeError):partial=True;continue
                if item.get('library')!=lib or not isinstance(item.get('stage'),str) or item['stage'] not in SECTIONS:partial=True;continue
                if lib in libraries:add(lib,title,item['stage'],'arr',ARR_REASONS[reason]+' Historical observation only; recheck through the existing Arr import/review flow.')
    counts={key:sum(row['kind']==key for row in rows) for key in LABELS}
    matching=[row for row in rows if (kind=='all' or row['kind']==kind) and
              (library=='all' or row['library']==library) and query.casefold() in row['title'].casefold()]
    matching.sort(key=lambda row:(row['library'],row['title'].casefold(),row['stage'],row['kind']))
    pages=max(1,(len(matching)+24)//25);page=min(page,pages)
    return dict(items=matching[(page-1)*25:page*25],matched=len(matching),counts=counts,page=page,pages=pages,
                query=query,kind=kind,library=library,complete=bool(libraries) and not unavailable,
                arr_partial=partial,latest=latest)
