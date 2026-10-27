"""Recovery metadata cannot change images or overwrite existing roots."""
from copy import deepcopy
from xml.etree import ElementTree as ET
import pytest
from test_unraid_update_review import fixture, REFERENCE, SECRET
from scripts.unraid_update_production_prepare import replacement_metadata


def inputs():
    root, current = fixture()
    current.update(State={'Running': False}, Image='sha256:'+'b'*64)
    current['HostConfig']['RestartPolicy']={'Name':'no'}
    image={'Id':current['Image'],'RepoDigests':[REFERENCE],'Config':{'Env':['PATH=/usr/bin']}}
    return dict(current=current,image=image,template=ET.tostring(root),
        environment=dict(item.split('=',1) for item in current['Config']['Env']),
        reference=REFERENCE,host_logs='/new-private/logs',host_control='/new-private/control',attempt='a'*64)


def test_template_and_create_payload_preserve_tokens_ports_and_media_safety():
    args=inputs(); original=deepcopy(args)
    payload, raw=replacement_metadata(**args)
    root=ET.fromstring(raw)
    assert args == original
    assert root.find("Config[@Target='/app/logs']").text == '/new-private/logs'
    assert root.find("Config[@Target='/sqlite-control']").text == '/new-private/control'
    assert 'INTEGRATION_API_TOKEN='+SECRET in payload['Env']
    assert payload['HostConfig']['ReadonlyRootfs'] is True
    media=next(x for x in payload['HostConfig']['Mounts'] if x['Target']=='/media')
    assert media['ReadOnly'] is True and media['Source']=='/private-fixture/media'
    assert payload['HostConfig']['PortBindings']==args['current']['HostConfig']['PortBindings']


@pytest.mark.parametrize('change', ['running','image','reference','overlap','writable'])
def test_unreviewed_recovery_refused(change):
    args=inputs()
    if change=='running': args['current']['State']['Running']=True
    if change=='image': args['image']['Id']='sha256:'+'c'*64
    if change=='reference': args['reference']=REFERENCE+'bad'
    if change=='overlap': args['host_logs']='/private-fixture/media/subdir'
    if change=='writable': args['current']['Mounts'][0]['RW']=True
    with pytest.raises(ValueError): replacement_metadata(**args)
