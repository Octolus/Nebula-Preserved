using System;
using System.Collections.Generic;

namespace NebulaPreservation
{
    // Native Type5 is informational but Confirm still emits ordinary C2S26.
    // This authored local correlator retires only a previously sent notice.
    // No friendship, inventory, event-file, clock or networking dependencies.
    public sealed class NebulaInformationalNotifications
    {
        public sealed class Rejected : Exception
        {
            public readonly string Code;
            public Rejected(string code) : base(code) { Code = code; }
        }

        private sealed class Pending
        {
            public string Guid;
            public double Expires;
        }

        private readonly Dictionary<string, Pending> pending = new Dictionary<string, Pending>(StringComparer.Ordinal);
        private readonly double ttlSeconds;
        private readonly int capacity;
        public int PendingCount => pending.Count;

        public NebulaInformationalNotifications(double ttlSeconds = 300, int capacity = 256)
        {
            if (!Finite(ttlSeconds) || ttlSeconds <= 0 || ttlSeconds > 86400 || capacity <= 0 || capacity > 10000)
                throw new ArgumentOutOfRangeException("Invalid informational notification policy");
            this.ttlSeconds = ttlSeconds;
            this.capacity = capacity;
        }

        public void Record(string recipientGuid, string sourceName, int sourcePlatform, double nowUnix)
        {
            Validate(recipientGuid, sourceName, sourcePlatform, nowUnix);
            Expire(nowUnix);
            string key = Key(recipientGuid, sourceName, sourcePlatform);
            if (!pending.ContainsKey(key) && pending.Count >= capacity)
                throw new Rejected("informational_notification_capacity");
            double expires = nowUnix + ttlSeconds;
            if (!Finite(expires)) throw new Rejected("invalid_informational_notification_time");
            // Native unread Type5 is also deduplicated by source/platform.
            // A repeated successful send refreshes this single pending key.
            pending[key] = new Pending {Guid = recipientGuid, Expires = expires};
        }

        public void Accept(string recipientGuid, string sourceName, int sourcePlatform, int notificationType, double nowUnix)
        {
            Validate(recipientGuid, sourceName, sourcePlatform, nowUnix);
            if (notificationType != 5) throw new Rejected("unsupported_informational_notification_type");
            Expire(nowUnix);
            string key = Key(recipientGuid, sourceName, sourcePlatform);
            if (!pending.Remove(key)) throw new Rejected("uncorrelated_informational_notification_acceptance");
        }

        public void Disconnect(string recipientGuid)
        {
            if (recipientGuid == null) return;
            var remove = new List<string>();
            foreach (var pair in pending) if (pair.Value.Guid == recipientGuid) remove.Add(pair.Key);
            foreach (string key in remove) pending.Remove(key);
        }

        public int Expire(double nowUnix)
        {
            if (!Finite(nowUnix) || nowUnix < 0) throw new Rejected("invalid_informational_notification_time");
            var remove = new List<string>();
            foreach (var pair in pending) if (pair.Value.Expires <= nowUnix) remove.Add(pair.Key);
            foreach (string key in remove) pending.Remove(key);
            return remove.Count;
        }

        private static string Key(string guid, string name, int platform) => guid + "\u001f" + name + "\u001f" + (platform == 0 ? "0" : "1");
        private static bool Finite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);
        private static void Validate(string guid, string name, int platform, double now)
        {
            Token(guid); Token(name);
            if (platform != 0 && platform != 1) throw new Rejected("invalid_informational_notification_platform");
            if (!Finite(now) || now < 0) throw new Rejected("invalid_informational_notification_time");
        }
        private static void Token(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length > 512 || value.IndexOf('#') >= 0)
                throw new Rejected("invalid_informational_notification_identity");
            foreach (char c in value) if (c < 32) throw new Rejected("invalid_informational_notification_identity");
        }
    }
}
