"""EntryData wire helpers derived from static client evidence.

The flat preset helper uses the shipped 450/462 public fields. Generic helpers
accept ordered schema fields {name,type}, where type is a primitive name,
{"enum": [names]}, {"array": element_type}, or {"object": ordered_fields}.
They implement the observable stream grammar, not CLR object construction or
native array reuse. All inputs are offline data; no game or network is started.
"""
import argparse
import json
import math
import struct
from pathlib import Path


def take_value(raw,offset):
    """Return raw UTF-16 value text and next byte offset; prefix is one code unit."""
    if offset+2>len(raw):raise ValueError('Missing EntryData length prefix')
    count=int.from_bytes(raw[offset:offset+2],'little')-0x24
    if count<0:raise ValueError('EntryData length prefix below 0x24')
    end=offset+2+count*2
    if end>len(raw):raise ValueError('Truncated EntryData value')
    return raw[offset+2:end].decode('utf-16le','surrogatepass'),end


def encode_value_texts(values):
    """Encode original lexical tokens without changing float formatting.

    Pass the decoder's token value_text strings to preserve wire spelling. None
    means the native null sentinel; there is no escaping or delimiter.
    """
    result=[]
    for value in values:
        value='nulls' if value is None else value
        if not isinstance(value,str):raise TypeError('EntryData lexical value must be str or None')
        size=len(value.encode('utf-16le','surrogatepass'))//2
        if size+0x24>0xffff:raise ValueError('Value exceeds one UTF16 length-prefix code unit')
        result.append(chr(size+0x24)+value)
    return ''.join(result)


def decode_entry_fields(text,fields,max_array_elements=4096):
    """Decode an explicitly ordered schema, including arrays/nested EntryData.

    A null token returns None; native DeserializeFields instead skips assignment
    and retains the destination's constructor/current value. Nested objects must
    be nonnull, as the native stream has no usable null-object marker.
    """
    raw=text.encode('utf-16le','surrogatepass')
    offset=0
    def token():
        nonlocal offset
        value,offset=take_value(raw,offset)
        return value
    def read_type(kind):
        if isinstance(kind,dict) and 'object' in kind:
            return {field['name']:read_type(field['type']) for field in kind['object']}
        value=token()
        if value=='nulls':return None
        if isinstance(kind,dict):
            if 'array' in kind:
                count=int(value,10)
                if not 0<=count<=max_array_elements:raise ValueError('Array length outside configured bound')
                return [read_type(kind['array']) for _ in range(count)]
            if 'enum' in kind:
                if value not in kind['enum']:
                    try:int(value,10)
                    except ValueError:raise ValueError('Unknown enum token '+value) from None
                return value
            raise ValueError('Unknown EntryData type descriptor')
        if kind=='string':return value
        if kind=='bool':
            if value.lower() not in ('true','false'):raise ValueError('Invalid Boolean token')
            return value.lower()=='true'
        if kind in ('int','long'):
            number=int(value,10)
            bits=32 if kind=='int' else 64
            if not -(1<<(bits-1))<=number<(1<<(bits-1)):raise ValueError('Integer token out of range')
            return number
        if kind in ('float','double'):
            number=float(value)
            if not math.isfinite(number):raise ValueError('Non-finite floating token')
            return struct.unpack('<f',struct.pack('<f',number))[0] if kind=='float' else number
        raise ValueError('Unknown EntryData primitive '+str(kind))
    result={field['name']:read_type(field['type']) for field in fields}
    if offset!=len(raw):raise ValueError('Trailing data after final EntryData field')
    return result


def encode_entry_fields(values,fields):
    """Emit explicit fields and nested arrays using canonical primitive spelling.

    Float/double inputs MUST be lexical strings. This deliberately avoids
    pretending Python formatting is byte-identical to this Unity IL2CPP runtime.
    Null class elements are rejected: the native writer can emit a marker but
    its class-element reader recurses without checking that marker.
    """
    def write_type(value,kind):
        if isinstance(kind,dict) and 'object' in kind:
            if value is None:raise ValueError('Nested EntryData objects must be nonnull')
            return ''.join(write_type(value[field['name']],field['type']) for field in kind['object'])
        if value is None:return encode_value_texts([None])
        if isinstance(kind,dict):
            if 'array' in kind:
                return encode_value_texts([str(len(value))])+''.join(write_type(item,kind['array']) for item in value)
            if 'enum' in kind:
                lexical=str(value)
                if lexical not in kind['enum']:
                    try:int(lexical,10)
                    except ValueError:raise ValueError('Unknown enum token '+lexical) from None
                return encode_value_texts([lexical])
            raise ValueError('Unknown EntryData type descriptor')
        if kind=='string':
            if not isinstance(value,str):raise TypeError('String field requires str')
            lexical=value
        elif kind=='bool':
            if not isinstance(value,bool):raise TypeError('Boolean field requires bool')
            lexical='True' if value else 'False'
        elif kind in ('int','long'):
            if not isinstance(value,int) or isinstance(value,bool):raise TypeError('Integer field requires int')
            bits=32 if kind=='int' else 64
            if not -(1<<(bits-1))<=value<(1<<(bits-1)):raise ValueError('Integer value out of range')
            lexical=str(value)
        elif kind in ('float','double'):
            if not isinstance(value,str):raise TypeError('Floating field requires explicit invariant lexical str')
            if not math.isfinite(float(value)):raise ValueError('Non-finite floating value')
            lexical=value
        else:raise ValueError('Unknown EntryData primitive '+str(kind))
        return encode_value_texts([lexical])
    return ''.join(write_type(values[field['name']],field['type']) for field in fields)


def schema_for_gender(gender,schemas):
    if gender not in ('MALE','FEMALE'):raise ValueError('Expected exact MALE or FEMALE')
    name='JsonClasses.Preset'+('Male' if gender=='MALE' else 'Female')+'Json'
    return next(t for t in schemas if t['full_name']==name)


def decode_flat_preset(text,gender,schemas):
    schema=schema_for_gender(gender,schemas)
    name=schema['full_name']
    raw=text.encode('utf-16le','surrogatepass')
    offset=0
    preset={}
    tokens=[]
    for field in schema['fields']:
        before=offset
        value,offset=take_value(raw,offset)
        tokens.append({'field':field['name'],'value_text':value,'utf16_offset':before//2})
        if value=='nulls':
            if 'float' in field['type_and_modifiers']:raise ValueError('Null float field '+field['name'])
            preset[field['name']]=None
        elif 'float' in field['type_and_modifiers']:
            numeric=float(value)
            if not math.isfinite(numeric):raise ValueError('Non-finite float field '+field['name'])
            preset[field['name']]=struct.unpack('<f',struct.pack('<f',numeric))[0]
        else:
            preset[field['name']]=value
    if offset!=len(raw):raise ValueError('Trailing data after final preset field')
    return {'schema':name,'preset':preset,'tokens':tokens}


def build_id_assets_tablenames(preset,gender,catalog):
    """Validate slots; emit all IDs, then all corresponding category names.

    Unknown/ambiguous catalog rows cannot authorize items. Display names and
    lowercase bundle filenames are never substituted for item identifiers.
    """
    if gender not in ('MALE','FEMALE'):raise ValueError('Expected exact MALE or FEMALE')
    by_id={}
    conflicts=set()
    for row in catalog['items']:
        if row.get('category_conflict'):conflicts.add(row['item_id'])
        if row['gender']==gender and row['category']:
            by_id.setdefault(row['item_id'],set()).add(row['category'])
    ids=[]
    categories=[]
    for index in range(1,41):
        item=preset['item'+str(index)]
        if item=='null':continue
        if not isinstance(item,str) or not item:raise ValueError('Invalid item slot '+str(index))
        if item in ids:raise ValueError('Duplicate item ID in preset: '+item)
        if item in conflicts:raise ValueError('Conflicting manifest categories for item: '+item)
        tables=by_id.get(item,set())
        if len(tables)!=1:raise ValueError('Unknown or ambiguous item/category for '+gender+': '+item)
        category=next(iter(tables))
        if '!' in item or '!' in category:raise ValueError('Unexpected delimiter in catalog')
        ids.append(item)
        categories.append(category)
    return {'data':'!'.join(ids+categories)}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input',type=Path,help='UTF-8 file containing only the EntryData serialized preset')
    ap.add_argument('--gender',choices=['MALE','FEMALE'],required=True)
    ap.add_argument('--schemas',type=Path,default=Path(__file__).resolve().parents[1] / 'protocol/avatar-metadata-schemas.json')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    result=decode_flat_preset(args.input.read_text(encoding='utf-8-sig'),args.gender,json.loads(args.schemas.read_text()))
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'schema':result['schema'],'fields':len(result['preset'])}))

if __name__=='__main__':
    main()

