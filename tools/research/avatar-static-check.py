"""Check offline avatar fixtures and EntryData grammar; never launch the game."""

from _research_paths import workspace, output_root, game_path
import hashlib
import json
import struct
from pathlib import Path
import avatar_entry_codec as codec


def main():
    root=(workspace() / 'results/protocol')
    schemas=json.loads((root/'avatar-metadata-schemas.json').read_text())
    catalog=json.loads((root/'avatar-asset-catalog.json').read_text())
    defaults=json.loads((root/'avatar-default-catalog.json').read_text())['defaults']
    checks=[]
    def passed(name,**details):checks.append({'check':name,**details,'result':'pass'})
    def rejects(name,call):
        try:call()
        except (ValueError,OverflowError,UnicodeError,TypeError):passed(name)
        else:raise AssertionError(name)
    for gender in ('MALE','FEMALE'):
        fixture=json.loads((root/('avatar-neutral-'+gender.lower()+'.json')).read_text())
        fields=codec.schema_for_gender(gender,schemas)['fields']
        texts=[]
        for field in fields:
            value=fixture[field['name']]
            texts.append(str(value) if 'float' in field['type_and_modifiers'] else value)
        wire=codec.encode_value_texts(texts)
        decoded=codec.decode_flat_preset(wire,gender,schemas)
        for field in fields:
            name=field['name']
            if 'float' in field['type_and_modifiers']:
                assert struct.pack('<f',fixture[name])==struct.pack('<f',decoded['preset'][name]),name
            else:assert fixture[name]==decoded['preset'][name],name
        assert codec.encode_value_texts(t['value_text'] for t in decoded['tokens'])==wire
        passed('flat fixture roundtrip and lexical preservation '+gender,field_count=len(fields))
        assert codec.build_id_assets_tablenames(fixture,gender,catalog)==defaults[gender]['id_assets_tablenames_json']
        passed('fixture item slots match native default catalog '+gender)
        rejects('trailing EntryData rejected '+gender,lambda:codec.decode_flat_preset(wire+'$',gender,schemas))
    text=codec.encode_value_texts(['\U0001f408','# ! null','',None])
    assert ord(text[0])==0x26
    offset=0
    raw=text.encode('utf-16le')
    actual=[]
    for _ in range(4):
        value,offset=codec.take_value(raw,offset)
        actual.append(value)
    assert actual==['\U0001f408','# ! null','','nulls']
    passed('UTF16 surrogate pair, delimiters, empty string and null sentinel')
    for name,raw in [('missing',b''),('negative count',b'\x00\x00'),('truncation',b'\x26\x00a\x00')]:
        rejects(name+' prefix rejected',lambda raw=raw:codec.take_value(raw,0))
    fields=[{'name':'players','type':{'array':{'object':[
        {'name':'name','type':'string'},{'name':'PS4ID','type':'string'},
        {'name':'GUID','type':'string'},{'name':'ready','type':'bool'},
        {'name':'color','type':'int'}]}}},
        {'name':'currentTime','type':'long'},
        {'name':'state','type':{'enum':['Free','Rejected','Awaiting','Ready','Playing']}},
        {'name':'turnIndex','type':'int'},
        {'name':'names','type':{'array':'string'}}]
    values={'players':[{'name':'local #!\U0001f408','PS4ID':'123','GUID':'local','ready':True,'color':2}],
            'currentTime':1234567890123,'state':'Ready','turnIndex':-1,'names':['a',None,'']}
    wire=codec.encode_entry_fields(values,fields)
    assert codec.decode_entry_fields(wire,fields)==values
    passed('synthetic nested object array, string array, enum name, bool, int64 roundtrip')
    fields=[{'name':'v','type':{'array':'string'}}]
    assert codec.decode_entry_fields(codec.encode_entry_fields({'v':[]},fields),fields)=={'v':[]}
    assert codec.decode_entry_fields(codec.encode_entry_fields({'v':None},fields),fields)=={'v':None}
    passed('empty array differs from null token')
    report={'evidence_type':'offline fixture and parser boundary checks; not a game/network interoperability test',
            'runtime_tested':False,'codec_sha256':hashlib.sha256(Path(codec.__file__).read_bytes()).hexdigest(),'checks':checks}
    (root/'avatar-static-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(checks),'results':'all pass','target_runtime_started':False}))


if __name__=='__main__':main()
