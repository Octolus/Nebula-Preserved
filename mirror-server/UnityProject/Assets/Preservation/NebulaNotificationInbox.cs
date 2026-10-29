using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;

namespace NebulaPreservation
{
    // Pure gift/reward inbox policy. No filesystem, clock, Unity, Mirror,
    // connection, process, background work or entitlement mutation.
    public sealed class NebulaNotificationInbox
    {
        [Serializable] public sealed class Entry
        {
            public string event_id;
            public string target_ps4_id;
            public string source_username;
            public int source_platform;
            public int notification_type;
            public string arguments;
            public long ticks;
        }

        [Serializable] public sealed class Snapshot
        {
            public int format_version;
            public double generation;
            public Entry[] entries;
        }

        [Serializable] public sealed class Acknowledgement
        {
            public int format_version = 1;
            public string event_id;
            public string target_ps4_id;
            public string guid;
            public string source_username;
            public int source_platform;
            public int notification_type;
            public double accepted_at;
        }

        public sealed class Delivery
        {
            public readonly string EventId;
            public readonly string TargetAccountId;
            public readonly string Guid;
            public readonly string Payload;
            internal readonly Entry Notice;
            internal Delivery(Entry notice, string guid)
            {
                Notice = Copy(notice);
                EventId = notice.event_id;
                TargetAccountId = notice.target_ps4_id;
                Guid = guid;
                Payload = "19#" + notice.source_username + "#" + notice.source_platform.ToString(Invariant) +
                    "#" + notice.notification_type.ToString(Invariant) + "#" + notice.arguments + "#" + notice.ticks.ToString(Invariant);
            }
        }

        public sealed class Rejected : Exception
        {
            public readonly string Code;
            public Rejected(string code) : base(code) { Code = code; }
        }

        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
        private readonly List<Entry> entries = new List<Entry>();
        private readonly Dictionary<string, Delivery> inflight = new Dictionary<string, Delivery>(StringComparer.Ordinal);
        private readonly HashSet<string> accepted = new HashSet<string>(StringComparer.Ordinal);
        private double generation = double.NaN;

        public void Replace(Snapshot snapshot, double nowUnix)
        {
            if (snapshot == null || snapshot.format_version != 1 || snapshot.entries == null ||
                snapshot.entries.Length > 10000 || !Fresh(snapshot.generation, nowUnix) ||
                (Finite(generation) && snapshot.generation < generation))
                throw new Rejected("invalid_notification_snapshot");
            var validated = new List<Entry>();
            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (Entry entry in snapshot.entries)
            {
                Validate(entry);
                if (!ids.Add(entry.event_id)) throw new Rejected("duplicate_notification_event");
                validated.Add(Copy(entry));
            }
            // Replacement is all-or-nothing. In-flight entries may not change
            // meaning under the same immutable event ID.
            foreach (Delivery delivery in inflight.Values)
            {
                Entry same = validated.Find(x => x.event_id == delivery.EventId);
                if (same != null && !Same(same, delivery.Notice)) throw new Rejected("changed_notification_event");
            }
            entries.Clear(); entries.AddRange(validated); generation = snapshot.generation;
            accepted.RemoveWhere(x => !ids.Contains(x));
            var removed = new List<string>();
            foreach (var pair in inflight) if (!ids.Contains(pair.Value.EventId)) removed.Add(pair.Key);
            foreach (string key in removed) inflight.Remove(key);
        }

        public IReadOnlyList<Delivery> Peek(string accountId, string guid, double nowUnix)
        {
            Token(accountId, false); Token(guid, false);
            var result = new List<Delivery>();
            if (!Fresh(generation, nowUnix)) return new ReadOnlyCollection<Delivery>(result);
            var keys = new HashSet<string>(inflight.Keys, StringComparer.Ordinal);
            foreach (Entry entry in entries)
            {
                string key = Key(entry.target_ps4_id, entry.source_username, entry.notification_type, entry.source_platform);
                if (entry.target_ps4_id != accountId || accepted.Contains(entry.event_id) || !keys.Add(key)) continue;
                result.Add(new Delivery(entry, guid));
            }
            return new ReadOnlyCollection<Delivery>(result);
        }

        // Call only after the real transport accepted this exact delivery.
        public void MarkQueued(Delivery delivery)
        {
            if (delivery == null) throw new Rejected("invalid_notification_delivery");
            string key = Key(delivery.TargetAccountId, delivery.Notice.source_username,
                delivery.Notice.notification_type, delivery.Notice.source_platform);
            Entry current = entries.Find(x => x.event_id == delivery.EventId);
            if (current == null || !Same(current, delivery.Notice) || accepted.Contains(delivery.EventId) || inflight.ContainsKey(key))
                throw new Rejected("stale_notification_delivery");
            inflight.Add(key, delivery);
        }

        // C2S26 contains no event ID, arguments or timestamp. Match only an
        // event actually queued to this account/session and sender/type key.
        // Persist the returned receipt before calling MarkAccepted.
        public Acknowledgement Accept(string accountId, string guid, string sourceName, int type, int sourcePlatform, double nowUnix)
        {
            Token(accountId, false); Token(guid, false); Token(sourceName, false);
            if ((type != 3 && type != 4) || (sourcePlatform != 0 && sourcePlatform != 1) || !Finite(nowUnix) || nowUnix < 0)
                throw new Rejected("unsupported_inbox_acceptance");
            Delivery delivery;
            if (!inflight.TryGetValue(Key(accountId, sourceName, type, sourcePlatform), out delivery) || delivery.Guid != guid)
                throw new Rejected("uncorrelated_inbox_acceptance");
            return new Acknowledgement {event_id = delivery.EventId, target_ps4_id = accountId, guid = guid,
                source_username = sourceName, source_platform = sourcePlatform, notification_type = type, accepted_at = nowUnix};
        }

        public void MarkAccepted(Acknowledgement ack)
        {
            if (ack == null || ack.format_version != 1 || !Finite(ack.accepted_at) || ack.accepted_at < 0)
                throw new Rejected("invalid_inbox_receipt");
            string key = Key(ack.target_ps4_id, ack.source_username, ack.notification_type, ack.source_platform);
            Delivery delivery;
            if (!inflight.TryGetValue(key, out delivery) || delivery.Guid != ack.guid || delivery.EventId != ack.event_id)
                throw new Rejected("uncorrelated_inbox_receipt");
            accepted.Add(delivery.EventId);
            inflight.Remove(key);
        }

        public void Disconnect(string guid)
        {
            var remove = new List<string>();
            foreach (var pair in inflight) if (pair.Value.Guid == guid) remove.Add(pair.Key);
            foreach (string key in remove) inflight.Remove(key);
        }

        private static bool Fresh(double value, double now) => Finite(value) && Finite(now) &&
            value >= 0 && now - value <= 15 && value - now <= 5;
        private static bool Finite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);
        private static string Key(string account, string source, int type, int platform) =>
            account + "\u001f" + source + "\u001f" + type.ToString(Invariant) + "\u001f" + platform.ToString(Invariant);
        private static void Token(string value, bool empty)
        {
            if (value == null || (!empty && value.Length == 0) || value.Length > 512 || value.IndexOf('#') >= 0)
                throw new Rejected("invalid_notification_token");
            foreach (char c in value) if (c < 32) throw new Rejected("invalid_notification_token");
        }
        private static void Validate(Entry entry)
        {
            if (entry == null || entry.event_id == null || entry.event_id.Length != 32)
                throw new Rejected("invalid_notification_event");
            foreach (char c in entry.event_id) if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))
                throw new Rejected("invalid_notification_event");
            Token(entry.target_ps4_id, false); Token(entry.source_username, false); Token(entry.arguments, true);
            if ((entry.source_platform != 0 && entry.source_platform != 1) ||
                (entry.notification_type != 3 && entry.notification_type != 4) ||
                entry.ticks < DateTime.MinValue.Ticks || entry.ticks > DateTime.MaxValue.Ticks ||
                (entry.notification_type == 4 && entry.arguments != ""))
                throw new Rejected("unsupported_notification_event");
        }
        private static Entry Copy(Entry value) => new Entry {event_id = value.event_id, target_ps4_id = value.target_ps4_id,
            source_username = value.source_username, source_platform = value.source_platform,
            notification_type = value.notification_type, arguments = value.arguments, ticks = value.ticks};
        private static bool Same(Entry a, Entry b) => a.event_id == b.event_id && a.target_ps4_id == b.target_ps4_id &&
            a.source_username == b.source_username && a.source_platform == b.source_platform &&
            a.notification_type == b.notification_type && a.arguments == b.arguments && a.ticks == b.ticks;
    }
}
