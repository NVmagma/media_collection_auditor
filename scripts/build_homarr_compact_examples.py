"""Generate compact Homarr templates using the JSX features we have checked."""
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'examples'/'integrations'
VARIANTS=(('oldest-waiting','10 oldest waiting','oldest-waiting',None),
          ('movies-leaving-soon','Movies leaving soon','leaving-soon','Movies'),
          ('tv-leaving-soon','TV leaving soon','leaving-soon','TV'))


def date_expression(item,field):
    value=item+'.'+field
    positions=((5,6),'/',(8,9),'/',(0,1,2,3),' ',(11,12),':',(14,15))
    parts=[]
    for part in positions:
        if isinstance(part,str):parts.append(json.dumps(part))
        else:parts.extend(value+'['+str(index)+']' for index in part)
    return value+'?.length >= 16 ? '+' + '.join(parts)+' : "Date unavailable"'


def template(title,view,library):
    waiting=view=='oldest-waiting'
    accent='#60a5fa' if waiting else '#fbbf24'
    tint='rgba(59,130,246,0.14)' if waiting else 'rgba(245,158,11,0.14)'
    stage='WAITING' if waiting else 'HOLDING'
    field='since' if waiting else 'estimated_removal_stage_at'
    date_label='Waiting since' if waiting else 'Est. removal stage'
    guard=f' || data.titles?.library_filter !== {json.dumps(library)}' if library else ''
    empty='No waiting tracking records' if waiting else 'No '+('TV' if library=='TV' else 'movie')+' tracking records in Holding'
    rows=[]
    for index in range(10):
        item=f'data.titles.items[{index}]'
        image=f'<Image src={{{item}.poster_url}} alt={{{item}.title}} w={{36}} h={{54}} fit="cover" radius="sm" />'
        rows.append(f'''      {{{item} ? (
        <Group wrap="nowrap" align="center" gap={{8}} style={{{{ border: "1px solid #334155", borderLeft: "3px solid {accent}", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}}}>
          {{{item}.poster_url ? (
            {item}.jellyfin_url ? <Anchor href={{{item}.jellyfin_url}} target="_blank" aria-label={{{item}.title}} style={{{{ flexShrink: 0 }}}}>{image}</Anchor> : {image}
          ) : <Text w={{36}} h={{54}} style={{{{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}}}>{{{item}.library === "TV" ? "TV" : "FILM"}}</Text>}}
          <Stack gap={{2}} style={{{{ minWidth: 0, flex: 1 }}}}>
            <Text size="sm" fw={{600}} title={{{item}.title}} style={{{{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}}}>{index+1}. {{{item}.title}}</Text>
            <Group wrap="nowrap" gap={{6}}>
              <Text style={{{{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "{accent}", backgroundColor: "{tint}", padding: "1px 6px", borderRadius: "999px" }}}}>{stage}</Text>
              <Text size="xs" style={{{{ color: "#94a3b8" }}}}>{{{item}.library === "TV" ? "TV show" : "Movie"}}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{{{ color: "#cbd5e1" }}}}>{date_label}: {{{date_expression(item,field)}}}</Text>
          </Stack>
        </Group>
      ) : null}}''')
    return f'''<Stack gap={{6}}>
  <Text fw={{700}}>{title}</Text>
  {{status.titles?.loading ? (
    <Text size="sm" role="status">Refreshing titles...</Text>
  ) : !status.titles?.ok || data.titles?.schema_version !== 1 || data.titles?.status !== "advisory_only" || data.titles?.view !== "{view}"{guard} || !data.titles?.items ? (
    <Text size="sm" role="status">Title list unavailable</Text>
  ) : data.titles.items.length === 0 ? (
    <Text size="sm">{empty}</Text>
  ) : (
    <Stack gap={{6}}>
{chr(10).join(rows)}
      {{data.titles.truncated ? <Text size="xs">Showing 10 of {{data.titles.total_records}} tracking records.</Text> : null}}
    </Stack>
  )}}
</Stack>
'''


def outputs():
    result={}
    for name,title,view,library in VARIANTS:
        prefix='homarr-'+name+'-compact'
        jsx=template(title,view,library)
        request={'source':'default','method':'GET','path':'/api/v1/titles/'+view,'kind':'query',
                 'trigger':'load','auth':'inherit','permission':'view','cacheSeconds':0}
        if library:request['query']={'library':library}
        requests={'titles':request}
        definition={'$schema':'homarr-custom-widget-v2','name':'Auditor: '+title+' (compact)',
            'description':'Read-only tracking records; freshness unverified. Holding dates are estimates, not deletion dates.',
            'sources':{'default':{'type':'http','name':'Auditor','baseUrl':'https://auditor.example.invalid',
                                'networkScope':'private','auth':'bearer'}},
            'requests':requests,'options':{},'template':jsx}
        result[prefix+'-template.example.jsx']=jsx
        result[prefix+'-requests.example.json']=json.dumps(requests,indent=2)+'\n'
        result[prefix+'-widget.example.json']=json.dumps(definition,indent=2,ensure_ascii=False)+'\n'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for name,content in outputs().items():
        path=ROOT/name
        if args.check:
            if not path.is_file() or path.read_text()!=content:raise SystemExit('Compact example needs regeneration: '+name)
        else:path.write_text(content)

if __name__=='__main__':main()
