# Optional mouse-look experiment

`patch_mouse_look.py` creates a separate `globalgamemanagers` candidate. It
copies Unity's original `Mouse X` and `Mouse Y` rows to the existing
`rightstick1horizontal` and `rightstick1vertical` camera axes. The vertical row
is inverted to match the shipped keyboard camera convention.

The script requires the caller to provide the exact SHA-256 of the reviewed
input file, refuses to overwrite output, serializes twice, and verifies that
every unrelated Unity object remains byte-identical. It does **not** install or
launch anything.

```powershell
python patch_mouse_look.py `
  --input "C:\path\to\globalgamemanagers" `
  --expected-sha256 <reviewed-input-sha256> `
  --output .\build\globalgamemanagers `
  --report .\build\mouse-look-report.json
```

Status: experimental and not runtime-accepted. Camera direction, sensitivity,
window focus, mouse UI behavior, and reliable cursor release remain open.
The generated game asset is intentionally excluded from Git.
