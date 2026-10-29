using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace NebulaPreservation
{
    // Same-host, short-lived routing between instances sharing one state root.
    // Original social wire fields are constructed by the receiver from current
    // trusted identities. No peer supplies an arbitrary wire payload or endpoint.
    public sealed class NebulaSocialMailbox
    {
        [Serializable] public sealed class Envelope
        {
            public int format_version = 1;
            public string event_id, kind, source_guid, target_guid, source_account, target_account;
            public string source_instance, target_instance, text;
            public int value;
            public double created_at, expires_at;
        }
        public sealed class Rejected : Exception
        {
            public readonly string Code;
            public Rejected(string code) : base(code) { Code = code; }
        }
        private readonly string root, instanceId;
        private readonly Func<Envelope, string> encode;
        private readonly Func<string, Envelope> decode;
        private readonly Dictionary<string, double> seen = new Dictionary<string, double>(StringComparer.Ordinal);
        public NebulaSocialMailbox(string stateRoot, string instanceId,
            Func<Envelope, string> encode, Func<string, Envelope> decode)
        {
            if (!SafeInstance(instanceId)) throw new Rejected("social_relay_invalid_instance");
            root = Path.GetFullPath(Path.Combine(stateRoot, "social-relay"));
            this.instanceId = instanceId;
            this.encode = encode ?? throw new ArgumentNullException(nameof(encode));
            this.decode = decode ?? throw new ArgumentNullException(nameof(decode));
        }
        public void Enqueue(Envelope entry, double now)
        {
            Validate(entry, now);
            if (entry.source_instance != instanceId) throw new Rejected("social_relay_source_instance");
            string folder = DirectoryFor(entry.target_instance);
            Directory.CreateDirectory(folder);
            if (Directory.EnumerateFiles(folder, "*.json").Take(513).Count() >= 512)
                throw new Rejected("social_relay_capacity");
            string path = Path.Combine(folder, entry.event_id + ".json");
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (var writer = new StreamWriter(stream, new System.Text.UTF8Encoding(false)))
                    writer.Write(encode(entry));
                File.Move(temporary, path); // immutable; concurrent duplicate cannot overwrite
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        public int Drain(double now, Action<Envelope> deliver, Action<string> rejected)
        {
            if (!Finite(now) || now < 0) throw new Rejected("social_relay_invalid_clock");
            foreach (string id in seen.Where(x => x.Value <= now).Select(x => x.Key).ToArray()) seen.Remove(id);
            string folder = DirectoryFor(instanceId);
            if (!Directory.Exists(folder)) return 0;
            int delivered = 0;
            foreach (string path in Directory.EnumerateFiles(folder, "*.json").OrderBy(x => x, StringComparer.Ordinal).Take(128))
            {
                string claim = path + ".processing." + Guid.NewGuid().ToString("N");
                try { File.Move(path, claim); }
                catch (FileNotFoundException) { continue; }
                catch (IOException) { continue; }
                try
                {
                    if (new FileInfo(claim).Length > 32768) throw new Rejected("social_relay_oversize");
                    Envelope entry;
                    using (var stream = new FileStream(claim, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete))
                    using (var reader = new StreamReader(stream, new System.Text.UTF8Encoding(false, true)))
                        entry = decode(reader.ReadToEnd());
                    Validate(entry, now);
                    if (Path.GetFileName(path) != entry.event_id + ".json" || entry.target_instance != instanceId)
                        throw new Rejected("social_relay_destination_mismatch");
                    if (seen.ContainsKey(entry.event_id)) throw new Rejected("social_relay_duplicate");
                    if (seen.Count >= 4096) throw new Rejected("social_relay_seen_capacity");
                    // Best effort for currently online sessions, not an offline inbox.
                    // Claim-before-callback avoids concurrent duplicate delivery.
                    seen.Add(entry.event_id, entry.expires_at);
                    deliver(entry);
                    delivered++;
                }
                catch (Rejected error) { rejected?.Invoke(error.Code); }
                catch (Exception) { rejected?.Invoke("social_relay_invalid_or_stale_delivery"); }
                finally { if (File.Exists(claim)) File.Delete(claim); }
            }
            return delivered;
        }
        private string DirectoryFor(string id)
        {
            if (!SafeInstance(id)) throw new Rejected("social_relay_invalid_instance");
            string path = Path.Combine(root, id);
            // Shared root is operator-controlled. Reject existing junctions so
            // a mailbox cannot silently redirect writes out of that root.
            if ((Directory.Exists(root) && (File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0) ||
                (Directory.Exists(path) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0))
                throw new Rejected("social_relay_linked_directory");
            return path;
        }
        public static void Validate(Envelope x, double now)
        {
            if (x == null || x.format_version != 1 || !HexGuid(x.event_id) || !HexGuid(x.source_guid) || !HexGuid(x.target_guid) ||
                x.source_guid == x.target_guid || !SafeInstance(x.source_instance) || !SafeInstance(x.target_instance) ||
                !Token(x.source_account, 128) || !Token(x.target_account, 128) || x.source_account == x.target_account ||
                !Finite(now) || !Finite(x.created_at) || !Finite(x.expires_at) || x.created_at > now ||
                x.expires_at <= now || x.expires_at - x.created_at > 30 || x.expires_at <= x.created_at)
                throw new Rejected("social_relay_invalid_envelope");
            bool valid = (x.kind == "request" && (x.value == 0 || x.value == 1 || x.value == 6)) ||
                (x.kind == "accepted" && (x.value == 0 || x.value == 1)) ||
                (x.kind == "chat" && x.value == 1) ||
                ((x.kind == "typing" || x.kind == "stop_typing") && x.value == 0) ||
                (x.kind == "refresh" && x.value >= 21 && x.value <= 25);
            if (!valid || (x.kind == "chat" ? !Token(x.text, 4096) : !String.IsNullOrEmpty(x.text)))
                throw new Rejected("social_relay_invalid_kind_or_fields");
        }
        private static bool Token(string x, int max) => !String.IsNullOrEmpty(x) && x.Length <= max && x.IndexOfAny(new[] {'#','\0'}) < 0;
        private static bool Finite(double x) => !Double.IsNaN(x) && !Double.IsInfinity(x);
        private static bool HexGuid(string x) => x != null && x.Length == 32 && x.All(c => c >= '0' && c <= '9' || c >= 'a' && c <= 'f');
        private static bool SafeInstance(string x) => !String.IsNullOrEmpty(x) && x.Length <= 128 &&
            x.All(c => c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_' || c == '-');
    }
}
