"""Build explicit neutral avatar fixtures from shipped serialized assets.

These are preservation fixtures, not recovered original server profiles. No game
or network service is started. Metadata field spelling and native slot limits
are preserved exactly.
"""

from _research_paths import workspace, output_root, game_path
import argparse
import json
import re
from pathlib import Path


def walk(node):
    yield node
    for child in node['children']:
        yield from walk(child)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--protocol',type=Path,default=(workspace() / 'results/protocol'))
    args=ap.parse_args()
    schemas=json.loads((args.protocol/'avatar-metadata-schemas.json').read_text())
    source=json.loads((args.protocol/'avatar-prefab-baselines.json').read_text())
    defaults=json.loads((args.protocol/'avatar-default-catalog.json').read_text())['defaults']
    mats={m['name']:m for m in source['skin_materials']}
    result={}
    for gender in ('MALE','FEMALE'):
        title=gender.title()
        schema=next(t for t in schemas if t['full_name']=='JsonClasses.Preset'+title+'Json')
        nodes={n['name'].lower():n for n in walk(source['bases'][title+'Base'])}
        preset={}
        evidence={}

        def put(key,value,why):
            assert any(f['name']==key for f in schema['fields']),key
            preset[key]=value
            evidence[key]=why

        for field in schema['fields']:
            key=field['name']
            if 'float' in field['type_and_modifiers']:
                put(key,0.0,'CLR zero initialization; overridden below where serialized or native evidence supplies a value')
            else:
                put(key,None,'CLR null initialization; overridden below where serialized or native evidence supplies a value')

        for field in schema['fields']:
            key=field['name']
            match=re.fullmatch(r'(.+_jnt)_([st])_([xyz])',key)
            if match:
                bone,kind,axis=match.groups()
                # Historic JSON typo, retained on the wire. Native female bone reader
                # uses F_ch_c_stomach_jnt for this block of six position/scale values.
                bone=bone.replace('stomaf_ch','stomach')
                transform=nodes[bone.lower()]
                prop='local_scale' if kind=='s' else 'local_position'
                put(key,transform[prop][axis],f'{title}Base/{transform["name"]}.{prop}.{axis}; native Read{title}BonesNETGCloud')
            elif key in (title+'Root_x',title+'Root_y',title+'Root_z'):
                put(key,nodes[(title+'Base').lower()]['local_scale'][key[-1]],f'native Read{title}BonesNETGCloud stores {title}Base.localScale in the JSON Root fields')
            elif re.fullmatch(r'b\d+',key):
                put(key,0.0,'Serialized neutral head blend weights; native readers pad final blend slot with zero')
            elif re.fullmatch(r'itemColor\d+_[rgb]',key):
                put(key,1.0,'Default clothing material _Color is white; native ReadClothColorNETGCloud pads unused RGB values with 1.0')
            elif re.fullmatch(r'(hatItem|handItem[LR])_[trs]_[xyz]',key):
                put(key,1.0 if '_s_' in key else 0.0,'Native no-attachment identity transform: translation/rotation 0, scale 1')

        selected=defaults[gender]['items']
        for i in range(1,41):
            put('item'+str(i),selected[i-1]['item_id'] if i<=len(selected) else 'null','Native default-editor call order; ReadClothNETGCloud pads unused item slots with literal "null"')
        for key in ('idpreset','iduser'):
            put(key,'','Local fixture placeholder; backend must assign account/preset identity before returning')
        put('presetname','Default','Local preservation preset name; original service name unknown')
        foot=next(x for x in selected if x['category']=='CLOTH_BODY_FEET')
        heel=next(c['fields']['_type'] for c in source['wardrobe_components'][foot['item_id']] if c['class']=='HighHeel')
        put('highHeel','HighHeel'+str(heel),'Serialized HighHeel._type on the native default feet asset')

        body=mats[title+'Body'];face=mats[title+'Face'];eye=mats['Eye' if gender=='MALE' else 'Female_Eye']
        def color(prefix,material,prop):
            values=dict(material['properties']['m_Colors'])[prop]
            for component in 'rgba':
                key=prefix+'_'+component
                if key in preset:put(key,values[component],f'serialized {material["name"]}.{prop}.{component}; native Read{title}SkinNETGCloud mapping')
        def scalar(key,material,prop):
            put(key,dict(material['properties']['m_Floats'])[prop],f'serialized {material["name"]}.{prop}; native skin reader mapping')
        def texture(key,material,prop):
            value=material['texture_names'].get(prop)
            put(key,value if value is not None else 'null',f'serialized {material["name"]}.{prop} texture name, literal "null" when absent')

        color('skin_color',body,'_Color')
        scalar('skin_mixnormalmap',body,'_MixNormalMap')
        texture('skin_bodybumpmap' if gender=='MALE' else 'skin_Bodybumpmap',body,'_BumpMap')
        texture('skin_bodybumpmap2',body,'_BumpMap2')
        for i in range(1,4):texture('skin_tattoo'+str(i),body,'_MainTattoo'+str(i))
        color('skin_coloreyebrowhair',face,'_ColorEyeBrowHair')
        texture('skin_eyebrowhair',face,'_MainEyeBrowHair')
        scalar('skin_eyebrowhairmultiply',face,'_EyeBrowHairMultiply')
        texture('skin_facepaint',face,'_MainFacePaint')
        texture('skin_secondfacepaint',face,'_SecondFacePaint')
        color('skin_lipscolor',face,'_ColorLips')
        color('skin_coloreye',eye,'_Color')
        if gender=='MALE':
            color('skin_colorbodyhair',body,'_ColorBodyHair')
            texture('skin_bodyhair',body,'_MainBodyHair')
            color('skin_colorfacehair',face,'_ColorFaceHair')
            texture('skin_facehair',face,'_MainFaceHair')
            for prefix,value in [('skin_hairbasecolor',1.0),('skin_hairsecondcolor',0.6499999761581421),('skin_specularcolor',0.33000001311302185),('skin_beardcolor',0.6499999761581421)]:
                for c in 'rgb':put(prefix+'_'+c,value,'Native ReadMaleSkinNETGCloud capture defaults from float constants at VA181dd2e10/181dd3380/181dd3360; default outfit has no separate hairstyle/beard')
        else:
            texture('skin_tights',body,'_MainTights')
            texture('skin_facebumpmap',face,'_BumpMap')
            texture('skin_facebumpmap2',face,'_BumpMap2')
            for i in range(1,4):
                color('skin_coloreyeline'+str(i),face,'_ColorEyeLine'+str(i))
                color('skin_colorshadow'+str(i),face,'_ColorEyeShadow'+str(i))
            texture('skin_eyeline',face,'_EyeLine')
            texture('skin_eyeshadow',face,'_EyeShadow')
            color('skin_blushcolor',face,'_ColorBlush')
            hair_item=next(x for x in selected if x['category']=='CLOTH_HEAD_HAIRSTYLE')
            hair=next(m for m in source['wardrobe_materials'][hair_item['item_id']] if '_BaseColor' in dict(m['properties']['m_Colors']))
            color('skin_hairbasecolor',hair,'_BaseColor')
            color('skin_hairsecondcolor',hair,'_SecondColor')
            color('skin_specularcolor',hair,'_SpecularColor')

        untouched=[k for k,v in evidence.items() if v.startswith('CLR')]
        # The inspected current save builder and skin readers never assign these
        # retained legacy float fields, so actual newly constructed objects have zero.
        assert untouched==['skin_specularamount','skin_specularsize'],untouched
        for key in untouched:evidence[key]='Retained legacy float field: current native save/skin reader paths leave CLR zero initialization'
        assert len(preset)==len(schema['fields'])
        assert all(v is not None for v in preset.values())
        (args.protocol/f'avatar-neutral-{gender.lower()}.json').write_text(json.dumps(preset,indent=2),encoding='utf-8')
        result[gender]={'field_count':len(preset),'field_sources':evidence,
                        'id_assets_tablenames_json':defaults[gender]['id_assets_tablenames_json']}
    (args.protocol/'avatar-neutral-seed-evidence.json').write_text(json.dumps({
        'evidence_type':'static neutral fixture reconstruction from shipped assets and native readers',
        'runtime_tested':False,'original_server_defaults_recovered':False,
        'limitations':['These fixtures reconstruct the authored neutral client assets; original service-selected appearance values are unavailable.','idpreset and iduser are empty placeholders to replace from local account state. presetname Default is a local name.','No game, server, client, connection test or live account mutation occurred.','Native field mapping and serialized data support these values; runtime avatar construction remains untested.'],
        'presets':result},indent=2),encoding='utf-8')
    print(json.dumps({g:d['field_count'] for g,d in result.items()}))

if __name__=='__main__':
    main()
