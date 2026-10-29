The fixtures are produced by the preserved implementations, not by the Rust
implementation under test. From the crate directory, regenerate them with:

```powershell
$env:TEMP = "$PWD/build-temp"
$env:TMP = $env:TEMP
./tests/wire_csharp_vectors.ps1 -SourceRoot ../..
python -B ./tests/wire_python_vectors.py ../..
```

`wire_csharp_vectors.ps1` compiles the shipped C# NetworkReader and NetworkWriter,
reader/writer extensions through nullable Guid, the varint portion of Compression,
Extensions, Batcher, Unbatcher, MessagePacking through Unpack, Telepathy.Utils,
NebulaApplicationCrypto, NebulaSpawnState and NebulaMirrorCommands. Minimal Unity
value structs and pool/transport stubs allow these actual methods to execute
without launching Unity or a client. Each source's SHA256 is recorded in the
fixture. C# compile scratch files go to the crate's build-temp directory.

`wire_python_vectors.py` imports the actual backend/wire.py without writing
bytecode, cross-checks its encryption against C# output, and records block/Unicode
encryption, malformed ciphertext, request splitting, session GUID and ASCII JSON
vectors. Its fixture records the Python source SHA256. The Rust integration tests
consume both committed fixtures without requiring C#, Python, Unity or the
original source tree at test time.

The native DecryptClient wrapper caps ciphertext at 65532 characters; backend
decrypt has no length cap. Rust exposes these separately as decrypt_client and
decrypt. The Python session GUID implementation replaces one non-ASCII Unicode
scalar with one question mark. .NET ASCII encoding replaces an astral character's
two UTF-16 code units with two question marks. session_guid intentionally follows
the Python implementation; ASCII account IDs and hashes have identical results.

The serialization layer covers the primitive formats exercised by the preserved
server. These tests do not claim to implement every Unity type or to validate a
real client's full gameplay session. Command policy, ownership, quaternion
validation and spawn lifecycle behavior belong to the world implementation.
