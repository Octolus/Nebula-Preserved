"""Build11018722 original-client N2SavePreset ingress compensation.

ReadFemaleBonesNETGCloud582470 emits left-position, left-scale,
right-position, right-scale, but getPresetDataToSave3c6680 assigns them to
left-position, right-position, left-scale, right-scale JSON fields. Both
editor58f910 and world600200 consume the named, canonical order.

Only the original native HTTP writer needs this permutation. Canonical
storage, admin/neutral inputs, codec and response JSON must not call it.
See protocol/avatar-female-save-compensation.json for hashed evidence.
If the client's writer is corrected, version its ingress before accepting
it here: applying this involution to already canonical input corrupts it.
"""


def normalize_original_native_save(preset, gender):
    """Return canonical named fields without changing the decoded input."""
    result = dict(preset)
    if gender == "FEMALE":
        for axis in "xyz":
            right_position = "f_ch_r_pectoral_jnt_t_" + axis
            left_scale = "f_ch_l_pectoral_jnt_s_" + axis
            result[right_position], result[left_scale] = preset[left_scale], preset[right_position]
    return result
