using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;

namespace NebulaPreservation
{
    // Opt-in semantic bridge for native 8/9/10/94. Legacy peers never enter
    // this class. Once a peer sends 97, raw numeric fallback is forbidden.
    public sealed class NebulaInteractionRegistry
    {
        [Serializable] public sealed class TrustedEntry
        {
            public string kind, anchor, @class, item_id, classification;
            public int[] path;
            public int slot, ground_index, extension_arity;
        }
        [Serializable] public sealed class Ground
        { public string item_id; public int index; public float tx, ty, tz, r; }
        [Serializable] public sealed class TrustedInstance
        {
            public string instance_id, scene, epoch;
            public bool trusted, static_profile_available;
            public TrustedEntry[] static_entries, furniture_entries;
            public Ground[] ground_sig;
        }
        [Serializable] private sealed class TrustedRoot
        { public int format_version; public TrustedInstance[] instances; }
        [Serializable] public sealed class WireEntry
        {
            public string kind, anchor, @class, item_id;
            public int send_id, receive_id, slot, ground_index;
            public int[] path;
        }
        [Serializable] public sealed class WireDocument
        {
            public int v;
            public string source, scene;
            public long seq;
            public WireEntry[] entries;
            public Ground[] ground_sig;
        }
        public sealed class Delivery
        {
            public readonly string TargetGuid, Payload;
            public Delivery(string target, string payload) { TargetGuid = target; Payload = payload; }
        }
        public sealed class Registration
        {
            public readonly string Status, Reason;
            public readonly long Seq;
            public readonly IReadOnlyList<Delivery> Deliveries;
            internal Registration(string status, string reason, long seq, List<Delivery> deliveries = null)
            { Status = status; Reason = reason; Seq = seq; Deliveries = deliveries ?? new List<Delivery>(); }
        }
        public sealed class Rejected : Exception
        { public readonly string Code; public Rejected(string code) : base(code) { Code = code; } }

        private sealed class BoundEntry
        { public string Key, Kind; public int SendId, ReceiveId; }
        private sealed class Queued
        { public int Opcode; public string[] Args; }
        private sealed class Peer
        {
            public bool OptedIn, StaticReady, FurnitureReady;
            public long Seq = -1;
            public List<BoundEntry> Static = new List<BoundEntry>(), Furniture = new List<BoundEntry>();
            public readonly List<Queued> Queue = new List<Queued>();
            public string PendingJson;
            public double PendingUntil;
            public long ChunkSeq = -1;
            public int ChunkParts, ChunkNext, ChunkBytes;
            public double ChunkUntil;
            public readonly MemoryStream Chunks = new MemoryStream();
        }

        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
        private const int MaxEntries = 4096, MaxQueue = 64, MaxJson = 1024 * 1024;
        public const int MaxChunkBytes = 4096, MaxChunkCharacters = 6000, MaxChunkParts = 256;
        private readonly string instanceId, scene;
        private readonly Func<double> clock;
        private readonly Dictionary<string, Peer> peers = new Dictionary<string, Peer>(StringComparer.Ordinal);
        private readonly Dictionary<string, bool> genericStates = new Dictionary<string, bool>(StringComparer.Ordinal);
        private readonly Dictionary<string, string> genericActors = new Dictionary<string, string>(StringComparer.Ordinal);
        private readonly Dictionary<string, string[]> genericExtras = new Dictionary<string, string[]>(StringComparer.Ordinal);
        private readonly Dictionary<string, string> occupants = new Dictionary<string, string>(StringComparer.Ordinal);
        private TrustedInstance trusted;

        public NebulaInteractionRegistry(string instanceId, string scene, Func<double> clock = null)
        {
            this.instanceId = instanceId ?? throw new ArgumentNullException(nameof(instanceId));
            this.scene = scene ?? throw new ArgumentNullException(nameof(scene));
            this.clock = clock ?? (() => DateTime.UtcNow.Subtract(new DateTime(1970, 1, 1)).TotalSeconds);
        }

        public bool IsOptedIn(string guid) => guid != null && peers.TryGetValue(guid, out Peer peer) && peer.OptedIn;
        public bool IsReady(string guid) => guid != null && peers.TryGetValue(guid, out Peer peer) && Ready(peer);
        public bool RequiresReloadAfterRejectedClaim(string guid, int opcode) => opcode == 9 && IsOptedIn(guid);
        public bool HasTrustedProfile => trusted != null;
        public void Require(string guid) { State(guid).OptedIn = true; }

        public string[] RefreshTrusted(string json)
        {
            TrustedInstance next;
            try
            {
                if (String.IsNullOrEmpty(json) || json.Length > MaxJson) throw new Rejected("registry_trust_snapshot_invalid");
                TrustedRoot root = JsonUtility.FromJson<TrustedRoot>(json);
                if (root == null || root.format_version != 1 || root.instances == null)
                    throw new Rejected("registry_trust_snapshot_invalid");
                next = root.instances.SingleOrDefault(x => x != null && x.instance_id == instanceId);
                if (next == null || next.scene != scene || !next.trusted || !next.static_profile_available ||
                    next.static_entries == null || next.furniture_entries == null || next.ground_sig == null ||
                    String.IsNullOrEmpty(next.epoch))
                    throw new Rejected("registry_instance_not_trusted");
                BuildTrusted(next.static_entries, "initial"); BuildTrusted(next.furniture_entries, "furniture");
            }
            catch
            {
                InvalidateTrust();
                throw;
            }
            if (trusted != null && trusted.epoch == next.epoch)
            {
                if (!TrustedEqual(trusted.static_entries, next.static_entries, "initial") ||
                    !TrustedEqual(trusted.furniture_entries, next.furniture_entries, "furniture") ||
                    !GroundEqual(trusted.ground_sig, next.ground_sig))
                { InvalidateTrust(); throw new Rejected("registry_epoch_content_mismatch"); }
                trusted = next; return new string[0];
            }
            bool staticChanged = trusted != null && !TrustedEqual(trusted.static_entries, next.static_entries, "initial");
            trusted = next;
            if (peers.Count == 0) return new string[0];
            genericStates.Clear(); genericActors.Clear(); genericExtras.Clear(); occupants.Clear();
            var invalidated = new List<string>();
            foreach (KeyValuePair<string, Peer> pair in peers)
            {
                Peer peer = pair.Value;
                if (peer.FurnitureReady || (staticChanged && peer.StaticReady)) invalidated.Add(pair.Key);
                peer.FurnitureReady = false; peer.Furniture.Clear();
                if (staticChanged) { peer.StaticReady = false; peer.Static.Clear(); }
            }
            return invalidated.ToArray();
        }

        private void InvalidateTrust()
        {
            trusted = null;
            genericStates.Clear(); genericActors.Clear(); genericExtras.Clear(); occupants.Clear();
            foreach (Peer peer in peers.Values)
            {
                peer.StaticReady = false; peer.FurnitureReady = false;
                peer.Static.Clear(); peer.Furniture.Clear(); peer.PendingJson = null;
            }
        }

        public string AddChunk(string guid, long seq, int part, int parts, string encoded)
        {
            Peer peer = State(guid); peer.OptedIn = true;
            if (seq < 0 || parts < 1 || parts > MaxChunkParts || part < 0 || part >= parts ||
                String.IsNullOrEmpty(encoded) || encoded.Length > MaxChunkCharacters || encoded.Contains("=") ||
                encoded.Any(c => !((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                    (c >= '0' && c <= '9') || c == '-' || c == '_')))
                throw new Rejected("registry_chunk_invalid");
            if (peer.ChunkSeq < 0)
            {
                if (part != 0 || seq <= peer.Seq) throw new Rejected("registry_chunk_order");
                peer.ChunkSeq = seq; peer.ChunkParts = parts; peer.ChunkNext = 0;
                peer.ChunkBytes = 0; peer.ChunkUntil = clock() + 10.0; peer.Chunks.SetLength(0);
            }
            if (clock() > peer.ChunkUntil)
            {
                ResetChunks(peer); throw new Rejected("registry_chunk_timeout");
            }
            if (peer.ChunkSeq != seq || peer.ChunkParts != parts || peer.ChunkNext != part)
                throw new Rejected("registry_chunk_order");
            string base64 = encoded.Replace('-', '+').Replace('_', '/');
            base64 += new string('=', (4 - base64.Length % 4) % 4);
            byte[] bytes;
            try { bytes = Convert.FromBase64String(base64); }
            catch (FormatException) { throw new Rejected("registry_chunk_base64url_invalid"); }
            if (bytes.Length > MaxChunkBytes) throw new Rejected("registry_chunk_too_large");
            if (peer.ChunkBytes + bytes.Length > MaxJson)
            { ResetChunks(peer); throw new Rejected("registry_json_too_large"); }
            peer.Chunks.Write(bytes, 0, bytes.Length); peer.ChunkBytes += bytes.Length; peer.ChunkNext++;
            if (peer.ChunkNext != parts) return null;
            byte[] complete = peer.Chunks.ToArray(); ResetChunks(peer);
            try { return new UTF8Encoding(false, true).GetString(complete); }
            catch (DecoderFallbackException) { throw new Rejected("registry_utf8_invalid"); }
        }

        private static void ResetChunks(Peer peer)
        {
            peer.ChunkSeq = -1; peer.ChunkParts = peer.ChunkNext = peer.ChunkBytes = 0;
            peer.ChunkUntil = 0; peer.Chunks.SetLength(0);
        }

        public Registration Register(string guid, string json, IEnumerable<string> readyGuids)
        {
            if (String.IsNullOrEmpty(guid) || String.IsNullOrEmpty(json) || json.Length > MaxJson)
                throw new Rejected("registry_message_invalid");
            Peer peer = State(guid); peer.OptedIn = true;
            WireDocument doc = JsonUtility.FromJson<WireDocument>(json);
            if (doc == null || doc.v != 1 || doc.scene != scene || doc.seq <= peer.Seq || doc.entries == null ||
                doc.ground_sig == null || (doc.source != "initial" && doc.source != "load" && doc.source != "save"))
                throw new Rejected("registry_message_invalid");
            bool initial = doc.source == "initial";
            TrustedEntry[] expected = initial ? trusted?.static_entries : trusted?.furniture_entries;
            if (expected == null) throw new Rejected("registry_trust_not_loaded");
            if (initial && doc.ground_sig.Length != 0) throw new Rejected("registry_initial_has_ground_signature");
            if (!initial && !GroundEqual(doc.ground_sig, trusted.ground_sig))
            {
                if (doc.source == "save")
                {
                    peer.FurnitureReady = false; peer.Furniture.Clear();
                    genericStates.Clear(); genericActors.Clear(); genericExtras.Clear(); occupants.Clear();
                    peer.PendingJson = json; peer.PendingUntil = clock() + 10.0;
                    return new Registration("pending", GroundDifference(doc.ground_sig, trusted.ground_sig, doc.source, doc.seq), doc.seq);
                }
                throw new Rejected("registry_ground_signature_mismatch");
            }
            List<BoundEntry> bound = Bind(doc.entries, expected, initial ? "initial" : "furniture");
            List<BoundEntry> other = initial ? peer.Furniture : peer.Static;
            Collision(bound, other);
            if (initial) { peer.Static = bound; peer.StaticReady = true; }
            else { peer.Furniture = bound; peer.FurnitureReady = true; }
            peer.Seq = doc.seq; peer.PendingJson = null;
            var deliveries = new List<Delivery>();
            if (Ready(peer))
            {
                Queued[] queued = peer.Queue.ToArray(); peer.Queue.Clear();
                // Pre-map traffic can reference an old local numeric namespace.
                // A complete trusted descriptor supersedes it atomically; stale
                // queued IDs are discarded rather than poisoning registration.
                foreach (Queued item in queued)
                    try { deliveries.AddRange(HandleReady(guid, item.Opcode, item.Args, readyGuids)); }
                    catch (Rejected) { }
                deliveries.AddRange(Snapshot(guid));
            }
            return new Registration("accepted", "", doc.seq, deliveries);
        }

        public Registration RetryPending(string guid, IEnumerable<string> readyGuids)
        {
            Peer peer = State(guid);
            if (peer.PendingJson == null) return null;
            if (clock() > peer.PendingUntil) { peer.PendingJson = null; throw new Rejected("registry_pending_timeout"); }
            string json = peer.PendingJson;
            WireDocument doc = JsonUtility.FromJson<WireDocument>(json);
            if (!GroundEqual(doc.ground_sig, trusted.ground_sig))
                return new Registration("pending", GroundDifference(doc.ground_sig, trusted.ground_sig, doc.source, doc.seq), doc.seq);
            return Register(guid, json, readyGuids);
        }

        public IReadOnlyList<Delivery> Handle(string guid, int opcode, string[] args, IEnumerable<string> readyGuids)
        {
            Peer peer = State(guid);
            if (!peer.OptedIn) throw new Rejected("registry_peer_not_opted_in");
            if (!Ready(peer))
            {
                if (opcode != 8 && opcode != 94) throw new Rejected("registry_not_ready");
                if (peer.Queue.Count >= MaxQueue) throw new Rejected("registry_queue_limit");
                peer.Queue.Add(new Queued { Opcode = opcode, Args = (string[])args.Clone() });
                return new Delivery[0];
            }
            return HandleReady(guid, opcode, args, readyGuids);
        }

        public IReadOnlyList<Delivery> Disconnect(string guid, IEnumerable<string> readyGuids)
        {
            var output = new List<Delivery>();
            foreach (string key in occupants.Where(x => x.Value == guid).Select(x => x.Key).ToArray())
            {
                occupants.Remove(key);
                foreach (string target in ReadyTargets(readyGuids))
                    output.Add(new Delivery(target, Join(10, guid, Receive(target, key, "occupable").ToString(Invariant))));
            }
            peers.Remove(guid);
            return output;
        }

        private List<Delivery> HandleReady(string guid, int opcode, string[] args, IEnumerable<string> readyGuids)
        {
            if (args == null || args.Length < 2 || args[0] != guid) throw new Rejected("registry_session_not_owned");
            if (!Int32.TryParse(args[1], NumberStyles.Integer, Invariant, out int local) || local < 0)
                throw new Rejected("registry_id_invalid");
            string kind = opcode == 94 ? "generic" : "occupable";
            string key = Resolve(guid, local, kind);
            TrustedEntry rule = Rule(key);
            if (rule.classification != "ordinary") throw new Rejected("registry_semantic_key_denied");
            if (opcode == 8)
            {
                if (args.Length != 2) throw new Rejected("registry_field_count");
                if (occupants.TryGetValue(key, out string occupant))
                    return new List<Delivery> { new Delivery(guid, Join(9, guid, Receive(guid, key, kind).ToString(Invariant), occupant)) };
                return new List<Delivery> { new Delivery(guid, Join(10, "", Receive(guid, key, kind).ToString(Invariant))) };
            }
            if (opcode == 9)
            {
                if (args.Length != 2) throw new Rejected("registry_field_count");
                if (occupants.TryGetValue(key, out string occupant) && occupant != guid)
                    throw new Rejected("registry_occupable_claim_conflict");
                occupants[key] = guid;
                return ReadyTargets(readyGuids).Select(target => new Delivery(target,
                    Join(9, guid, Receive(target, key, kind).ToString(Invariant), guid))).ToList();
            }
            if (opcode == 10)
            {
                if (args.Length != 2 || !occupants.TryGetValue(key, out string occupant) || occupant != guid)
                    throw new Rejected("registry_occupable_not_owned");
                occupants.Remove(key);
                return ReadyTargets(readyGuids).Select(target => new Delivery(target,
                    Join(10, guid, Receive(target, key, kind).ToString(Invariant)))).ToList();
            }
            if (opcode != 94 || args.Length < 3 || args.Length - 3 != rule.extension_arity)
                throw new Rejected("registry_generic_arity");
            if (!Boolean.TryParse(args[2], out bool state)) throw new Rejected("registry_bool_invalid");
            foreach (string extra in args.Skip(3)) if (extra == null || extra.Length > 512 || extra.Contains("#"))
                throw new Rejected("registry_extension_invalid");
            if (genericStates.TryGetValue(key, out bool old) && old == state) return new List<Delivery>();
            genericStates[key] = state; genericActors[key] = guid; genericExtras[key] = args.Skip(3).ToArray();
            return ReadyTargets(readyGuids).Select(target => new Delivery(target,
                Join(94, new[] { guid, Receive(target, key, kind).ToString(Invariant), state ? "True" : "False" }
                    .Concat(args.Skip(3)).ToArray()))).ToList();
        }

        private List<Delivery> Snapshot(string guid)
        {
            var output = new List<Delivery>();
            foreach (KeyValuePair<string, bool> state in genericStates)
            {
                try
                {
                    var fields = new List<string> { genericActors[state.Key], Receive(guid, state.Key, "generic").ToString(Invariant), state.Value ? "True" : "False" };
                    fields.AddRange(genericExtras[state.Key]); output.Add(new Delivery(guid, Join(94, fields.ToArray())));
                }
                catch (Rejected) { }
            }
            return output;
        }

        private List<BoundEntry> Bind(WireEntry[] supplied, TrustedEntry[] expected, string ns)
        {
            if (supplied.Length != expected.Length || supplied.Length > MaxEntries) throw new Rejected("registry_incomplete");
            var rules = expected.ToDictionary(x => Key(ns, x.kind, x.anchor, x.path, x.@class, x.slot, x.ground_index, x.item_id), StringComparer.Ordinal);
            var result = new List<BoundEntry>(); var keys = new HashSet<string>(StringComparer.Ordinal);
            foreach (WireEntry entry in supplied)
            {
                if (entry == null || (entry.kind != "generic" && entry.kind != "occupable") || entry.send_id < 0 || entry.receive_id < 0 ||
                    entry.anchor == null || (ns == "initial" ? entry.anchor.Length == 0 : entry.anchor.Length != 0) ||
                    entry.path == null || entry.path.Any(x => x < 0) || entry.slot < 0 || entry.@class == null || entry.item_id == null ||
                    (entry.kind == "generic" && entry.send_id != entry.receive_id)) throw new Rejected("registry_entry_invalid");
                string key = Key(ns, entry.kind, entry.anchor, entry.path, entry.@class, entry.slot, entry.ground_index, entry.item_id);
                if (!rules.ContainsKey(key) || !keys.Add(key)) throw new Rejected("registry_unknown_or_duplicate_key");
                result.Add(new BoundEntry { Key = key, Kind = entry.kind, SendId = entry.send_id, ReceiveId = entry.receive_id });
            }
            if (keys.Count != rules.Count) throw new Rejected("registry_incomplete");
            return result;
        }

        private static void Collision(List<BoundEntry> first, List<BoundEntry> second)
        {
            var send = new HashSet<string>(); var receive = new HashSet<string>();
            foreach (BoundEntry item in first.Concat(second))
            {
                if (!send.Add(item.Kind + ":" + item.SendId) || !receive.Add(item.Kind + ":" + item.ReceiveId))
                    throw new Rejected("registry_source_namespace_collision");
            }
        }

        private string Resolve(string guid, int id, string kind)
        {
            Peer peer = State(guid);
            BoundEntry[] found = peer.Static.Concat(peer.Furniture).Where(x => x.Kind == kind && x.SendId == id).ToArray();
            if (found.Length != 1) throw new Rejected("registry_send_id_unbound");
            return found[0].Key;
        }
        private int Receive(string guid, string key, string kind)
        {
            Peer peer = State(guid);
            BoundEntry[] found = peer.Static.Concat(peer.Furniture).Where(x => x.Kind == kind && x.Key == key).ToArray();
            if (found.Length != 1) throw new Rejected("registry_receive_id_unbound");
            return found[0].ReceiveId;
        }
        private TrustedEntry Rule(string key)
        {
            string ns = key.StartsWith("initial|", StringComparison.Ordinal) ? "initial" : "furniture";
            TrustedEntry[] entries = ns == "initial" ? trusted.static_entries : trusted.furniture_entries;
            TrustedEntry rule = entries.SingleOrDefault(x => Key(ns, x.kind, x.anchor, x.path, x.@class, x.slot, x.ground_index, x.item_id) == key);
            if (rule == null) throw new Rejected("registry_rule_missing"); return rule;
        }
        private Peer State(string guid)
        { if (!peers.TryGetValue(guid, out Peer peer)) peers[guid] = peer = new Peer(); return peer; }
        private bool Ready(Peer peer) => peer.StaticReady && peer.FurnitureReady && trusted != null;
        private IEnumerable<string> ReadyTargets(IEnumerable<string> guids) => (guids ?? new string[0]).Where(IsReady).Distinct(StringComparer.Ordinal);
        private static string Key(string ns, string kind, string anchor, int[] path, string cls, int slot, int ground, string item) =>
            ns + "|" + kind + "|" + anchor + "|" + String.Join("/", path ?? new int[0]) + "|" + cls + "|" + slot.ToString(Invariant) + "|" + ground.ToString(Invariant) + "|" + item;
        private static Dictionary<string, TrustedEntry> BuildTrusted(TrustedEntry[] entries, string ns)
        {
            if (entries == null || entries.Length > MaxEntries) throw new Rejected("registry_trust_entries_invalid");
            var result = new Dictionary<string, TrustedEntry>(StringComparer.Ordinal);
            foreach (TrustedEntry entry in entries)
            {
                if (entry == null || (entry.kind != "generic" && entry.kind != "occupable") || entry.anchor == null ||
                    (ns == "initial" ? entry.anchor.Length == 0 : entry.anchor.Length != 0) || entry.path == null || entry.path.Any(x => x < 0) ||
                    entry.slot < 0 || entry.ground_index < -1 || String.IsNullOrEmpty(entry.@class) || entry.item_id == null ||
                    entry.extension_arity < 0 || entry.extension_arity > 32 ||
                    (entry.classification != "ordinary" && entry.classification != "deferred_minigame" &&
                     entry.classification != "separate_protocol"))
                    throw new Rejected("registry_trust_entry_invalid");
                string key = Key(ns, entry.kind, entry.anchor, entry.path, entry.@class, entry.slot, entry.ground_index, entry.item_id);
                if (result.ContainsKey(key)) throw new Rejected("registry_trust_duplicate_key"); result[key] = entry;
            }
            return result;
        }
        private static bool TrustedEqual(TrustedEntry[] left, TrustedEntry[] right, string ns)
        {
            Dictionary<string, TrustedEntry> a = BuildTrusted(left, ns), b = BuildTrusted(right, ns);
            if (a.Count != b.Count || a.Keys.Any(key => !b.ContainsKey(key))) return false;
            return a.All(pair => pair.Value.classification == b[pair.Key].classification &&
                pair.Value.extension_arity == b[pair.Key].extension_arity);
        }
        private static bool GroundEqual(Ground[] left, Ground[] right)
        {
            if (left == null || right == null || left.Length != right.Length) return false;
            for (int i = 0; i < left.Length; i++)
                if (left[i] == null || right[i] == null || left[i].item_id != right[i].item_id || left[i].index != right[i].index ||
                    Bits(left[i].tx) != Bits(right[i].tx) || Bits(left[i].ty) != Bits(right[i].ty) ||
                    Bits(left[i].tz) != Bits(right[i].tz) || Bits(left[i].r) != Bits(right[i].r)) return false;
            return true;
        }
        private static string GroundDifference(Ground[] observed, Ground[] expected, string source, long seq)
        {
            int observedCount = observed == null ? -1 : observed.Length;
            int expectedCount = expected == null ? -1 : expected.Length;
            var differences = new List<string>(); int total = observedCount == expectedCount ? 0 : 1;
            int count = Math.Min(Math.Max(observedCount, 0), Math.Max(expectedCount, 0));
            Action<int, string, string, string> add = (index, field, actual, wanted) =>
            {
                total++;
                if (differences.Count < 4) differences.Add("index=" + index.ToString(Invariant) +
                    ",field=" + field + ",observed=" + actual + ",expected=" + wanted);
            };
            for (int i = 0; i < count; i++)
            {
                Ground actual = observed[i], wanted = expected[i];
                if (actual == null || wanted == null)
                {
                    if (actual != wanted) add(i, "entry", actual == null ? "null" : "present", wanted == null ? "null" : "present");
                    continue;
                }
                if (actual.item_id != wanted.item_id) add(i, "item_id_hash", Hash(actual.item_id), Hash(wanted.item_id));
                if (actual.index != wanted.index) add(i, "index", actual.index.ToString(Invariant), wanted.index.ToString(Invariant));
                if (Bits(actual.tx) != Bits(wanted.tx)) add(i, "tx", Hex(actual.tx), Hex(wanted.tx));
                if (Bits(actual.ty) != Bits(wanted.ty)) add(i, "ty", Hex(actual.ty), Hex(wanted.ty));
                if (Bits(actual.tz) != Bits(wanted.tz)) add(i, "tz", Hex(actual.tz), Hex(wanted.tz));
                if (Bits(actual.r) != Bits(wanted.r)) add(i, "r", Hex(actual.r), Hex(wanted.r));
            }
            string reason = "awaiting_authoritative_ground_signature;source=" + (source ?? "") +
                ";seq=" + seq.ToString(Invariant) + ";observed_count=" + observedCount.ToString(Invariant) +
                ";expected_count=" + expectedCount.ToString(Invariant) + ";diff_total=" + total.ToString(Invariant);
            for (int i = 0; i < differences.Count; i++) reason += ";diff" + i.ToString(Invariant) + "=" + differences[i];
            return reason;
        }
        private static string Hex(float value) => "0x" + unchecked((uint)Bits(value)).ToString("x8", Invariant);
        private static string Hash(string value)
        {
            using (SHA256 sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value ?? ""))).Replace("-", "").ToLowerInvariant().Substring(0, 16);
        }
        private static int Bits(float value) { if (value == 0f) value = 0f; return BitConverter.ToInt32(BitConverter.GetBytes(value), 0); }
        private static string Join(int opcode, params string[] fields) => opcode.ToString(Invariant) + "#" + String.Join("#", fields);
    }
}
