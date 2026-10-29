param([string]$SourceRoot = (Join-Path $PSScriptRoot '../../..'))
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$env:TEMP = Join-Path $project 'build-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$mirror = Join-Path $SourceRoot 'mirror-server/UnityProject/Assets/Mirror/Runtime'
$preservation = Join-Path $SourceRoot 'mirror-server/UnityProject/Assets/Preservation'
function Read-Source([string]$file) {
    # Consolidate using directives so the original classes share one compilation.
    return ([IO.File]::ReadAllText($file) -replace '(?m)^using [^\r\n]+;\r?\n', '')
}
function Prefix-Source([string]$file, [string]$marker) {
    $text = Read-Source $file
    $offset = $text.IndexOf($marker, [StringComparison]::Ordinal)
    if ($offset -lt 0) { throw "Source marker missing: $marker" }
    return $text.Substring(0, $offset) + "`n    }`n}`n"
}
$sources = @(
    'using System; using System.IO; using System.Text; using System.Collections.Generic; using System.Runtime.CompilerServices; using System.Runtime.InteropServices; using System.Security.Cryptography; using UnityEngine; using Unity.Collections.LowLevel.Unsafe; using Mirror;',
    @'
namespace Unity.Collections.LowLevel.Unsafe { public static class UnsafeUtility {} }
namespace UnityEngine {
 public static class Debug { public static void LogError(object o) {} }
 public struct Vector2 { public float x,y; }
 public struct Vector3 { public float x,y,z; public Vector3(float x,float y,float z) {this.x=x;this.y=y;this.z=z;} }
 public struct Vector4 { public float x,y,z,w; }
 public struct Quaternion { public float x,y,z,w; public Quaternion(float x,float y,float z,float w) {this.x=x;this.y=y;this.z=z;this.w=w;} }
 public struct Vector2Int { public int x,y; } public struct Vector3Int { public int x,y,z; }
 public struct Color { public float r,g,b,a; } public struct Color32 { public byte r,g,b,a; }
 public struct Rect { public float x,y,w,h; } public struct Plane { public Vector3 n; public float d; }
 public struct Ray { public Vector3 o,d; } public struct Matrix4x4 { public float x; }
}
namespace Mirror {
 public interface NetworkMessage {}
 public struct CommandMessage { public uint netId; public byte componentIndex; public int functionHash; public ArraySegment<byte> payload; }
 public static class Channels { public const int Reliable=0, Unreliable=1; }
 public class Transport { public static Transport activeTransport=new Transport(); public int GetMaxPacketSize() { return 16384; } }
 public class NetworkWriterPooled : NetworkWriter {}
 public static class NetworkWriterPool { public static NetworkWriterPooled Get() { return new NetworkWriterPooled(); } public static void Return(NetworkWriterPooled w) {} }
}
'@,
    (Read-Source (Join-Path $mirror 'NetworkReader.cs')),
    (Read-Source (Join-Path $mirror 'NetworkWriter.cs'))
)
# Keep the exact shipped reader/writer extensions through GuidNullable; later
# extensions require Unity scenes and are outside the primitive wire contract.
foreach ($name in @('NetworkReaderExtensions.cs','NetworkWriterExtensions.cs')) {
    $text = Read-Source (Join-Path $mirror $name)
    $method = if ($name.StartsWith('NetworkReader')) { 'NetworkIdentity ReadNetworkIdentity' } else { 'void WriteNetworkIdentity' }
    $position = $text.IndexOf($method, [StringComparison]::Ordinal)
    if ($position -lt 0) { throw "No method boundary in $name" }
    $boundary = $text.LastIndexOf('        [MethodImpl(', $position, [StringComparison]::Ordinal)
    $sources += $text.Substring(0,$boundary) + "`n    }`n}`n"
}
$compression = Read-Source (Join-Path $mirror 'Compression.cs')
$position = $compression.IndexOf('        public static void CompressVarUInt', [StringComparison]::Ordinal)
$sources += "namespace Mirror { public static class Compression {`n" + $compression.Substring($position)
$sources += Read-Source (Join-Path $mirror 'Extensions.cs')
$sources += Read-Source (Join-Path $mirror 'Batching/Batcher.cs')
$sources += Read-Source (Join-Path $mirror 'Batching/Unbatcher.cs')
$sources += Prefix-Source (Join-Path $mirror 'MessagePacking.cs') '        // version for handlers with channelId'
$sources += Read-Source (Join-Path $mirror 'Transports/Telepathy/Telepathy/Utils.cs')
$sources += Read-Source (Join-Path $preservation 'NebulaApplicationCrypto.cs')
$sources += Read-Source (Join-Path $preservation 'NebulaSpawnState.cs')
$sources += Read-Source (Join-Path $preservation 'NebulaMirrorCommands.cs')
$sources += @'
public static class NebulaWireVectors {
 static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }
 static string Serialized(Action<NetworkWriter> action) { var w=new NetworkWriter(); action(w); return Hex(w.ToArray()); }
 static bool Rejected(Action action) { try { action(); return false; } catch { return true; } }
 public static Dictionary<string,object> Generate() {
  var output=new Dictionary<string,object>();
  string[] texts={"", "a", "0123456789abcdef", "é🚀#PS4", "guid#account#text#with#hashes#PS4"};
  var crypto=new List<object>();
  foreach (string text in texts) crypto.Add(new Dictionary<string,object>{{"plaintext",text},{"ciphertext",NebulaPreservation.NebulaApplicationCrypto.EncryptReply(text)}});
  output["crypto"]=crypto;
  var strings=new List<object>(); foreach(string text in new string[]{null,"","a","é🚀#","\0\t\r\n"}) strings.Add(new Dictionary<string,object>{{"value",text},{"hex",Serialized(w=>w.WriteString(text))}}); output["strings"]=strings;
  ulong[] values={0,1,239,240,241,255,256,2287,2288,67823,67824,16777215,16777216,4294967295,4294967296,1099511627775,1099511627776,281474976710655,281474976710656,72057594037927935,72057594037927936,ulong.MaxValue};
  var integers=new List<object>(); foreach(ulong value in values) integers.Add(new Dictionary<string,object>{{"value",value.ToString()},{"hex",Serialized(w=>Compression.CompressVarUInt(w,value))}}); output["varuint"]=integers;
  var signed=new List<object>(); foreach(long value in new long[]{long.MinValue,-123456789,-121,-1,0,1,120,121,long.MaxValue}) signed.Add(new Dictionary<string,object>{{"value",value.ToString()},{"hex",Serialized(w=>Compression.CompressVarInt(w,value))}}); output["varint"]=signed;
  output["primitives"]=Serialized(w=>{w.WriteByte(0xab);w.WriteSByte(-7);w.WriteUShort(0x1234);w.WriteShort(-300);w.WriteUInt(0x89abcdef);w.WriteInt(-123456789);w.WriteULong(0x0123456789abcdef);w.WriteLong(long.MinValue);w.WriteFloat(-0f);w.WriteFloat(float.PositiveInfinity);w.WriteDouble(-123.5);w.WriteBool(true);w.WriteBool(false);w.WriteChar('\ud800');});
  output["nullable"]=Serialized(w=>{w.WriteIntNullable(null);w.WriteIntNullable(-123);w.WriteBoolNullable(null);w.WriteBoolNullable(false);w.WriteBoolNullable(true);w.WriteFloatNullable(1.25f);w.WriteFloatNullable(null);w.WriteGuidNullable(null);w.WriteGuidNullable(new Guid("00112233-4455-6677-8899-aabbccddeeff"));});
  output["guid"]=Serialized(w=>w.WriteGuid(new Guid("00112233-4455-6677-8899-aabbccddeeff")));
  output["bytes"]=Serialized(w=>{w.WriteBytesAndSize((byte[])null);w.WriteBytesAndSize(new byte[0]);w.WriteBytesAndSize(new byte[]{0,128,255});});
  var hashes=new Dictionary<string,object>(); foreach(string text in new[]{"Mirror.ReadyMessage","Mirror.AddPlayerMessage","Mirror.CommandMessage","Mirror.RpcMessage","Mirror.SpawnMessage","Mirror.EntityStateMessage","é🚀",NebulaPreservation.NebulaMirrorCommands.SpeedSignature,NebulaPreservation.NebulaMirrorCommands.SyncSignature}) hashes[text]=text.GetStableHashCode(); output["hashes"]=hashes;
  var batcher=new Batcher(15); batcher.AddMessage(new ArraySegment<byte>(new byte[]{1,2,3}),1.5);batcher.AddMessage(new ArraySegment<byte>(new byte[]{4,5,6,7}),2.5);batcher.AddMessage(new ArraySegment<byte>(new byte[]{8}),3.5);batcher.AddMessage(new ArraySegment<byte>(new byte[20]),4.5);var batches=new List<string>();var batchWriter=new NetworkWriter();while(batcher.GetBatch(batchWriter)){batches.Add(Hex(batchWriter.ToArray()));batchWriter.Reset();}output["batches"]=batches;
  output["spawn_initial"]=Hex(NebulaPreservation.NebulaSpawnState.Initial(new Vector3(1,-2,3.5f),new Quaternion(0,0,0,1),4.5f));output["speed_delta"]=Hex(NebulaPreservation.NebulaSpawnState.SpeedDelta(4.5f));
  byte[] header=new byte[4]; Telepathy.Utils.IntToBytesBigEndianNonAlloc(0x123456,header);output["telepathy_header"]=Hex(header);
  var noncanonical=new NetworkReader(new byte[]{2,0x7b,0,0,0}); output["nullable_nonzero"]=noncanonical.ReadIntNullable();
  output["ascii_astral"]=Hex(Encoding.ASCII.GetBytes("🚀"));
  output["noncanonical_base64"]=NebulaPreservation.NebulaApplicationCrypto.DecryptClient("QrnGrub9EXAqpBYR/qr3Gx==");
  var malformed=new Dictionary<string,object>();
  malformed["string_invalid_utf8"]=Rejected(()=>new NetworkReader(new byte[]{3,0,255,255}).ReadString());
  malformed["string_truncated"]=Rejected(()=>new NetworkReader(new byte[]{2,0}).ReadString());
  malformed["string_limit"]=Rejected(()=>new NetworkWriter().WriteString(new string('a',32768)));
  malformed["nullable_truncated"]=Rejected(()=>new NetworkReader(new byte[]{1}).ReadIntNullable());
  malformed["bytes_size_overflow"]=Rejected(()=>new NetworkReader(new byte[]{255,255,255,255}).ReadBytesAndSize());
  malformed["bytes_truncated"]=Rejected(()=>new NetworkReader(new byte[]{4,0,0,0,1}).ReadBytesAndSize());
  malformed["bool_nonzero"]=new NetworkReader(new byte[]{2}).ReadBool();
  var unbatcher=new Unbatcher();malformed["batch_short_accepted"]=unbatcher.AddBatch(new ArraySegment<byte>(new byte[7]));
  malformed["batch_timestamp_only_accepted"]=unbatcher.AddBatch(new ArraySegment<byte>(new byte[8]));NetworkReader emptyMessage;double emptyTimestamp;malformed["batch_timestamp_only_has_message"]=unbatcher.GetNextMessage(out emptyMessage,out emptyTimestamp);
  output["malformed"]=malformed;
  return output;
 }
}
'@
Add-Type -TypeDefinition ($sources -join "`n") -Language CSharp -CompilerOptions '/unsafe'
$generated = [NebulaWireVectors]::Generate()
$sourceHashes = [ordered]@{}
foreach ($file in @('NetworkReader.cs','NetworkWriter.cs','NetworkReaderExtensions.cs','NetworkWriterExtensions.cs','Compression.cs','Extensions.cs','Batching/Batcher.cs','Batching/Unbatcher.cs','MessagePacking.cs','Transports/Telepathy/Telepathy/Utils.cs')) {
    $sourceHashes[('Assets/Mirror/Runtime/' + $file)] = (Get-FileHash -LiteralPath (Join-Path $mirror $file) -Algorithm SHA256).Hash.ToLowerInvariant()
}
foreach ($file in @('NebulaApplicationCrypto.cs','NebulaSpawnState.cs','NebulaMirrorCommands.cs')) {
    $sourceHashes[('Assets/Preservation/' + $file)] = (Get-FileHash -LiteralPath (Join-Path $preservation $file) -Algorithm SHA256).Hash.ToLowerInvariant()
}
$generated['source_sha256'] = $sourceHashes
$generated | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'wire_csharp_vectors.json') -Encoding utf8NoBOM
