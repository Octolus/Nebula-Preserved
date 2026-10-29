using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
using UnityEngine;

namespace NebulaPreservation
{
    // File interchange with the local HTTP store. This is local preservation
    // authentication, not Steam ticket validation or original backend policy.
    public sealed class NebulaInstanceAccounts
    {
        [Serializable]
        public sealed class Account
        {
            public string guid;
            public string ps4_id;
            public string username;
            public string platform;
            public string gender;
            public int resource_selection_schema;
            public string selected_companion, selected_locomotion;
            public long companion_revision, locomotion_revision;
            public string[] companion_ids;
            public string[] locomotion_ids;
            public bool wardrobe_active;
            public string wardrobe_instance_id;
            public double wardrobe_updated_at;
            public Vector3 position;
            public double position_updated_at;
            public double session_created_at;
            public string allocated_instance_id;
            public int moderation_schema;
            public bool chat_muted;
            public double chat_mute_until;

            public int PlatformNumber => platform == "PS4" ? 0 : 1;
            public bool ChatMuted(double now) => chat_muted && (chat_mute_until == 0 || now < chat_mute_until);
        }

        [Serializable]
        private sealed class Snapshot
        {
            public int format_version;
            public double generation;
            public Account[] accounts;
        }

        private readonly string path;
        private readonly Func<double> clock;
        private DateTime lastWrite;
        private long lastLength = -1;
        private double lastGeneration = -1;
        private Dictionary<string, Account> accounts = new Dictionary<string, Account>(StringComparer.Ordinal);

        public NebulaInstanceAccounts(string stateDirectory, Func<double> clock = null)
        {
            path = Path.Combine(stateDirectory, "instance-accounts.json");
            this.clock = clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0);
            Refresh(true);
        }

        public Account Find(string guid)
        {
            Refresh(false);
            return guid != null && accounts.TryGetValue(guid, out Account value) ? value : null;
        }

        public Account[] All()
        {
            Refresh(false);
            var result = new Account[accounts.Count];
            accounts.Values.CopyTo(result, 0);
            return result;
        }

        private void Refresh(bool force)
        {
            double now = clock();
            var info = new FileInfo(path);
            if (!info.Exists || info.Length <= 0 || info.Length > 16 * 1024 * 1024)
                throw new InvalidDataException("invalid_snapshot_file");
            if (!force && info.LastWriteTimeUtc == lastWrite && info.Length == lastLength)
            {
                RequireFresh(lastGeneration, now); // Cached authority also expires.
                return;
            }
            string text;
            // Allow the HTTP store to atomically replace the snapshot on
            // Windows while this process reads a consistent open file.
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
                                               FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(stream, new System.Text.UTF8Encoding(false, true))) text = reader.ReadToEnd();
            if (text.Length > 16 * 1024 * 1024) throw new InvalidDataException("snapshot_too_large");
            Dictionary<string, Policy> policies = ReadPolicies(text, out double generation);
            RequireFresh(generation, now);
            if (generation < lastGeneration) throw new InvalidDataException("snapshot_generation_regressed");
            Snapshot snapshot = JsonUtility.FromJson<Snapshot>(text);
            if (snapshot == null || snapshot.format_version != 1 || snapshot.accounts == null ||
                Double.IsNaN(snapshot.generation) || Double.IsInfinity(snapshot.generation))
                throw new InvalidDataException("invalid_snapshot_schema");
            if (snapshot.accounts.Length != policies.Count) throw new InvalidDataException("invalid_moderation_accounts");
            var next = new Dictionary<string, Account>(StringComparer.Ordinal);
            foreach (Account account in snapshot.accounts)
            {
                if (account == null || !IsGuid(account.guid) || String.IsNullOrEmpty(account.ps4_id) ||
                    account.ps4_id.Length > 128 || account.ps4_id.IndexOf('#') >= 0 ||
                    account.username == null || account.username.Length > 128 ||
                    (account.platform != "StandaloneWindows" && account.platform != "PS4") ||
                    (account.gender != "MALE" && account.gender != "FEMALE") || next.ContainsKey(account.guid))
                    throw new InvalidDataException("invalid_snapshot_account");
                if (!policies.TryGetValue(account.guid, out Policy policy))
                    throw new InvalidDataException("missing_moderation_account");
                // JsonUtility defaults missing fields to zero/false. Only the
                // independently checked, explicitly typed tokens grant policy.
                account.moderation_schema = 1;
                account.chat_muted = policy.muted;
                account.chat_mute_until = policy.until;
                // Older version1 exporters lacked resources. Missing arrays
                // mean no grant, so nonempty selections fail closed.
                account.companion_ids = ValidateResources(account.companion_ids);
                account.locomotion_ids = ValidateResources(account.locomotion_ids);
                account.selected_companion = account.selected_companion ?? "";
                account.selected_locomotion = account.selected_locomotion ?? "";
                if (account.resource_selection_schema != 1 || account.companion_revision < 0 || account.locomotion_revision < 0 ||
                    account.companion_revision > 9007199254740990L || account.locomotion_revision > 9007199254740990L ||
                    (account.selected_companion != "" && !Array.Exists(account.companion_ids, x => x == account.selected_companion)) ||
                    (account.selected_locomotion != "" && !Array.Exists(account.locomotion_ids, x => x == account.selected_locomotion)))
                    throw new InvalidDataException("invalid_resource_selection_snapshot");
                if (!Finite(account.wardrobe_updated_at) || !Finite(account.position_updated_at) ||
                    !Finite(account.session_created_at) || account.wardrobe_updated_at < 0 ||
                    account.position_updated_at < 0 || account.session_created_at < 0 ||
                    (account.wardrobe_active && String.IsNullOrEmpty(account.wardrobe_instance_id)) ||
                    (account.wardrobe_instance_id != null && (account.wardrobe_instance_id.Length > 128 || account.wardrobe_instance_id.IndexOf('#') >= 0)) ||
                    (account.allocated_instance_id != null && (account.allocated_instance_id.Length > 128 || account.allocated_instance_id.IndexOf('#') >= 0)) ||
                    !Finite(account.position.x) || !Finite(account.position.y) || !Finite(account.position.z))
                    throw new InvalidDataException("invalid_snapshot_lifecycle");
                next.Add(account.guid, account);
            }
            accounts = next;
            lastGeneration = generation;
            lastWrite = info.LastWriteTimeUtc;
            lastLength = info.Length;
        }

        private static void RequireFresh(double generation, double now)
        {
            if (!Finite(generation) || !Finite(now) || generation < 0 || now - generation > 15 || generation - now > 5)
                throw new InvalidDataException("stale_account_authority");
        }

        private sealed class Policy { public bool muted; public double until; }

        private static Dictionary<string, Policy> ReadPolicies(string text, out double generation)
        {
            var reader = new Fields(text);
            Dictionary<string, Fields.Slice> root = reader.Object();
            reader.End();
            if (reader.Raw(root, "format_version") != "1") throw new InvalidDataException("invalid_snapshot_version");
            generation = reader.Number(root, "generation");
            reader.Position = reader.Required(root, "accounts").start;
            reader.Expect('[');
            var policies = new Dictionary<string, Policy>(StringComparer.Ordinal);
            if (!reader.Take(']'))
            {
                do
                {
                    Dictionary<string, Fields.Slice> row = reader.Object();
                    string quoted = reader.Raw(row, "guid");
                    string guid = quoted.Length == 34 && quoted[0] == '"' && quoted[33] == '"' ? quoted.Substring(1, 32) : "";
                    string muted = reader.Raw(row, "chat_muted");
                    double until = reader.Number(row, "chat_mute_until");
                    if (!IsGuid(guid) || reader.Raw(row, "moderation_schema") != "1" ||
                        (muted != "true" && muted != "false") || until < 0 ||
                        policies.Count >= 16384 || policies.ContainsKey(guid))
                        throw new InvalidDataException("invalid_moderation_policy");
                    policies.Add(guid, new Policy {muted = muted == "true", until = until});
                } while (reader.Take(','));
                reader.Expect(']');
            }
            return policies;
        }

        // A bounded token scanner verifies authority field presence/types;
        // Unity JsonUtility still reads the existing account/vector schema.
        // Exported field names are canonical ASCII, with no escaped aliases.
        private sealed class Fields
        {
            public struct Slice { public int start, length; }
            private readonly string text;
            public int Position;
            private int tokens;
            private static readonly Regex NumberToken = new Regex(@"\A-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\z");
            public Fields(string text) { this.text = text; }
            private void Fail() { throw new InvalidDataException("invalid_account_json"); }
            private void Space() { while (Position < text.Length && " \r\n\t".IndexOf(text[Position]) >= 0) Position++; }
            public bool Take(char value) { Space(); if (Position < text.Length && text[Position] == value) { Position++; return true; } return false; }
            public void Expect(char value) { if (!Take(value)) Fail(); }
            public void End() { Space(); if (Position != text.Length) Fail(); }
            public Slice Required(Dictionary<string, Slice> fields, string name)
            { if (!fields.TryGetValue(name, out Slice value)) { Fail(); } return value; }
            public string Raw(Dictionary<string, Slice> fields, string name)
            { Slice value = Required(fields, name); return text.Substring(value.start, value.length); }
            public double Number(Dictionary<string, Slice> fields, string name)
            {
                string token = Raw(fields, name);
                if (!NumberToken.IsMatch(token) || !Double.TryParse(token, NumberStyles.Float, CultureInfo.InvariantCulture, out double value) || !Finite(value))
                    throw new InvalidDataException("invalid_account_number");
                return value;
            }
            private void String()
            {
                Expect('"');
                while (Position < text.Length)
                {
                    char value = text[Position++];
                    if (value == '"') return;
                    if (value < 32) Fail();
                    if (value != '\\') continue;
                    if (Position >= text.Length) Fail();
                    char escape = text[Position++];
                    if (escape == 'u')
                    {
                        for (int n = 0; n < 4; n++)
                            if (Position >= text.Length || "0123456789abcdefABCDEF".IndexOf(text[Position++]) < 0) Fail();
                    }
                    else if ("\"\\/bfnrt".IndexOf(escape) < 0) Fail();
                }
                Fail();
            }
            public Dictionary<string, Slice> Object(int depth = 0)
            {
                if (depth > 32) Fail();
                Expect('{');
                var fields = new Dictionary<string, Slice>(StringComparer.Ordinal);
                if (Take('}')) return fields;
                do
                {
                    Space(); int keyStart = Position; String();
                    string key = text.Substring(keyStart + 1, Position - keyStart - 2);
                    if (key.Length > 128 || key.IndexOf('\\') >= 0 || fields.Count >= 128 || fields.ContainsKey(key)) Fail();
                    Expect(':'); Space(); int start = Position; Value(depth + 1);
                    fields.Add(key, new Slice {start = start, length = Position - start});
                } while (Take(','));
                Expect('}'); return fields;
            }
            private void Value(int depth)
            {
                if (depth > 32 || ++tokens > 1000000) Fail();
                Space(); if (Position >= text.Length) Fail();
                char value = text[Position];
                if (value == '{') { Object(depth); return; }
                if (value == '[')
                {
                    Position++;
                    if (Take(']')) return;
                    do { Value(depth + 1); } while (Take(','));
                    Expect(']'); return;
                }
                if (value == '"') { String(); return; }
                int start = Position;
                while (Position < text.Length && " \t\r\n,]}".IndexOf(text[Position]) < 0) Position++;
                string token = text.Substring(start, Position - start);
                if (token != "true" && token != "false" && token != "null" && !NumberToken.IsMatch(token)) Fail();
            }
        }

        private static bool Finite(double value) => !Double.IsNaN(value) && !Double.IsInfinity(value);

        private static string[] ValidateResources(string[] values)
        {
            if (values == null) return Array.Empty<string>();
            if (values.Length > 1024) throw new InvalidDataException("invalid_snapshot_resources");
            var unique = new HashSet<string>(StringComparer.Ordinal);
            foreach (string value in values)
                if (String.IsNullOrEmpty(value) || value.Length > 256 || value.IndexOf('#') >= 0 ||
                    value.IndexOf('\0') >= 0 || !unique.Add(value))
                    throw new InvalidDataException("invalid_snapshot_resource_id");
            return values;
        }

        private static bool IsGuid(string value)
        {
            if (value == null || value.Length != 32) return false;
            foreach (char c in value)
                if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
            return true;
        }
    }
}
