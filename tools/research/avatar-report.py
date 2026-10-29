"""Write source-linked static avatar save and loading contracts."""

from _research_paths import workspace, output_root, game_path
import hashlib
import json
from pathlib import Path


def main():
    root=(workspace() / 'results/protocol')
    schemas=json.loads((root/'avatar-metadata-schemas.json').read_text())
    catalog=json.loads((root/'avatar-asset-catalog.json').read_text())
    methods={
        'ManagerPreset.Save':'58b560','NETGcloudEditor.getPresetDataToSave':'3c6680',
        'NETGcloudEditor.OnSend_SavePresetCoroutine.MoveNext':'3e3480',
        'NETGcloudEditor.OnSend_SavePresetExitCoroutine.MoveNext':'3e4220',
        'EntryData.Serialize':'6a65b0','EntryData.SerializeFields':'6a5d10',
        'EntryData.Deserialize':'6a59f0','EntryData.DeserializeFields':'6a5020',
        'EntryData.GetArrayObject':'6a5a50','EntryData.GetArrayValue':'6a5bb0',
        'EntryData.GetDataValue':'6a5cc0','EntryData.SetDataValue':'6a6630',
        'ManagerPreset.LoadDefaultMALEEditor':'57c4d0','ManagerPreset.LoadDefaultFEMALEEditor':'57b9a0',
        'NebulaPlayerAvatar.LoadPreset':'5f8770','NebulaPlayerAvatar.GetPresetGame':'5f7800',
        'NebulaPlayerAvatar.CreatePlayer':'5f6a80','NebulaPlayerAvatar.IsPresetCorrect':'5f8440',
        'NebulaPlayerAvatar.GetAssetNames':'5f7410','NebulaPlayerAvatar.AddDefaultFeetIfNeeded':'5f5c30',
        'NebulaPlayerAvatar.CREATEPLAYER':'5f5fb0','NebulaPlayerAvatar.CREATEPLAYER.MoveNext':'6033e0',
        'NebulaPlayerAvatar.InstantiateIndividualAsset':'5f7e00','NebulaPlayerAvatar.PostInstantiateAssets':'5fc840',
        'NebulaPlayerAvatar.UpdateBlends':'5ff480','NebulaPlayerAvatar.ModifySkin':'5f8960',
        'NebulaPlayerAvatar.WriteMaleBones':'601920','NebulaPlayerAvatar.WriteFemaleBones':'600200',
        'Persistency.AddPurchasedAssets':'615f30','Persistency.GetDatas':'6162f0'}
    evidence=[]
    for name,rva in methods.items():
        path=(workspace() / 'work/evidence/ghidra/functions')/(rva+'.c')
        evidence.append({'method':name,'rva':'0x'+rva,'va':hex(0x180000000+int(rva,16)),
                         'pseudocode_file':str(path),'pseudocode_sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None})
    preset_schemas={}
    for gender,title in [('MALE','Male'),('FEMALE','Female')]:
        schema=next(t for t in schemas if t['full_name']=='JsonClasses.Preset'+title+'Json')
        preset_schemas[gender]={'class':schema['full_name'],'field_count':len(schema['fields']),
            'field_order_evidence':'Type.GetFields native calls; metadata declaration order, not alphabetic or JSON object sorting',
            'ordered_fields':[{'name':f['name'],'type':'float' if 'float' in f['type_and_modifiers'] else 'string',
                               'managed_layout_offset':f['managed_layout_offset']} for f in schema['fields']],
            'neutral_fixture':'avatar-neutral-'+gender.lower()+'.json'}
    result={
        'status':'static reconstruction, runtime interoperability not tested',
        'game':{'app_id':919290,'build_id':11018722,'unity':'2021.3.9f1','binary_sha256':'c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac'},
        'evidence':evidence,
        'save':{'method':'GET','route':'/N2SavePreset','query_parameter':'data',
            'request_plaintext':'SessionGUID#PS4ID#presetName#numericGender#EntryDataPreset',
            'request_fields':[{'name':'SessionGUID','source':'PS4Info singleton+0xe8'},
                              {'name':'PS4ID','source':'PS4Info singleton+0xd8'},
                              {'name':'presetName','source':'caller argument; repeated inside flat preset.presetname'},
                              {'name':'numericGender','source':'caller integer ToString; 0 male, 1 female'},
                              {'name':'EntryDataPreset','source':'getPresetDataToSave -> EntryData.Serialize, not JSON'}],
            'transport_steps':['Concatenate five logical fields with four # characters','AES.Encrypt plaintext using existing client AES wrapper','Uri.EscapeDataString ciphertext','Insert into N2SavePreset?data={0}'],
            'response_steps':['AES.Decrypt response text','Split plaintext on #','Require first field exact true','Boolean.Parse second field must be true','Invoke PresetSaved or close wardrobe for SaveExit'],
            'success_plaintext':'true#true',
            'save_exit_uses_same_route_and_body':True,
            'implementation_constraints':['Split incoming plaintext at first four # separators so # in serialized values remains intact.','Client does not escape # in header fields: reject # in preset names in the local backend.','Validate the session and bind local ownership server-side; the client success parser does not verify any returned identity.','Use the numeric gender to select the exact ordered preset schema; field names and float positions differ.']},
        'entry_data':{'prefix_formula':'one UTF16 code unit with unsigned value 0x24 + UTF16 code-unit count of following lexical value',
            'value_encoding':'System.String content; AES wrapper performs its own text-to-byte conversion',
            'concatenation':'prefix+value directly repeated, with no separators, quotes, terminators or escaping',
            'empty_string':'one code unit U+0024 with zero following units',
            'null_lexical_sentinel':'nulls','null_token':'U+0029 followed by nulls',
            'null_semantics':'DeserializeFields skips assignment and retains constructor/current value; literal string nulls is therefore not round-trip representable as a string',
            'unused_item_sentinel':'null (ordinary four-character application string; different from nulls)',
            'float_format':'Single.ToString(InvariantCulture); decoder Double.Parse with invariant NumberStyles0xa7 then casts to Single',
            'other_scalar_format':'Object.ToString; Boolean True/False, integers decimal, enums usually declared symbolic names',
            'enum_parse':'Enum.Parse(declaredType,value), accepts declared names and underlying numeric strings',
            'array':'prefixed decimal count followed by elements; scalar/string elements each prefixed; EntryData object element is its fields directly without wrapper',
            'array_null':'prefixed nulls; native reader skips assignment',
            'nested_object':'fields recursively concatenated directly; nonnull nested EntryData objects required for interoperable streams',
            'native_array_state':'GetArrayObject can retain a larger existing destination array; GetArrayValue constructs missing EntryData elements. Generic helper decodes only stream values, not this reuse behavior.',
            'unsupported_cases':['Native null nested class serialization omits it; no corresponding unambiguous null-object grammar.','Native null class-array element emits nulls but class-element reader recurses without checking; helpers reject this case.','Full framework culture/NaN/Infinity/flags-enum behavior is not modeled by the bounded local helper.'],
            'local_parser_bounds':'Reject negative/truncated lengths, extra trailing data, nonfinite preset floats; enforce array count bound. Native prefix arithmetic wraps beyond one UTF16 unit; local emitter rejects overflow.',
            'module':'../tools/avatar_entry_codec.py','validation':'avatar-static-validation.json'},
        'preset_schemas':preset_schemas,
        'items':{'slot_count':40,'padding':'literal null','identifiers':'original-case prefab/asset identifiers, not lowercase bundle filenames',
            'id_assets_json_class':'JsonClasses.IdAssetsTablenamesJson',
            'id_assets_data_grammar':'IDs joined by !, then all corresponding table/category names joined by !; two halves, not alternating pairs',
            'example':'idA!idB!CLOTH_BODY_TORSO!CLOTH_BODY_LEGS',
            'validation':'Use known gender+item identity with exactly one nonconflicting manifest category; reject unknown and category_conflict rows.',
            'catalog':'avatar-asset-catalog.json','default_catalog':'avatar-default-catalog.json',
            'catalog_summary':catalog['summary']},
        'inventory':{'class':'PurchasesData','cloths':'list of original-case item IDs',
            'clothsName':'parallel display/name strings indexed by cloths index; not category/table names',
            'list_constraints':'Initialize all13 item lists and13 matching Name lists. Names list must contain at least one entry per corresponding ID.',
            'native_getdatas_result':'Persistency.AssetData {asset = ids[i], name = names[i]}',
            'original_labels_available':False,'local_name_policy':'An explicit local label or item ID fallback is reconstructed metadata, not a recovered commercial name.'},
        'neutral_fixtures':{'source':'shipped authored-neutral base hierarchy, default wardrobe prefab materials/components and native readers',
            'provenance':'avatar-neutral-seed-evidence.json','original_server_default_recovered':False,
            'important_values':['Root_x/y/z are localScale (1,1,1), not position.','Male92 blend slots and female88 include a final padded zero.','Female default foot has HighHeel._type1, hence HighHeel1; male0.','Six female stomach field spellings use f_ch_c_stomaf_ch_jnt_ prefix, matching metadata typo.','idpreset/iduser are empty placeholders; backend must assign local identity.']},
        'unknowns':['Original service-selected numerical appearance defaults, entitlements and commercial names.','Nine shipped item rows have neither category nor gender evidence in their paths;24 manifest rows have conflicting category hints.','Runtime reflection field order and actual avatar instantiation/asset dependency resolution have not been tested.','A complete multiplayer server and every networking subsystem are outside this avatar contract.']}
    (root/'avatar-save-contract.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'contract':'avatar-save-contract.json','native_methods':len(evidence),'missing_pseudocode':[e['method'] for e in evidence if not e['pseudocode_sha256']]}))


if __name__=='__main__':main()
