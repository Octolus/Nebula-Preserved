using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;

namespace NebulaPreservation
{
    // Replacement local policy, constrained by the native packet schemas.
    // Contains no sockets. Identity and recipients are supplied by the instance.
    public sealed class NebulaSocialState
    {
        public sealed class Actor
        {
            public readonly string Guid, AccountId, Username, Platform;
            public readonly int PlatformNumber;
            public Actor(string guid, string accountId, string username, string platform, int platformNumber)
            { Guid = guid; AccountId = accountId; Username = username; Platform = platform; PlatformNumber = platformNumber; }
        }

        public sealed class Rejected : Exception
        {
            public readonly string Code;
            public Rejected(string code) : base(code) { Code = code; }
        }

        [Serializable] private sealed class RelationRow
        { public string ps4_id, target, target_platform, kind; }
        [Serializable] private sealed class Snapshot
        { public int format_version; public double generation; public RelationRow[] relations; }
        [Serializable] private sealed class FriendEvent
        {
            public int format_version = 1;
            public string event_id, operation, actor_ps4_id, other_ps4_id;
            public double created_at;
            public string policy = "correlated_online_request_v1";
        }
        [Serializable] private sealed class Pending
        {
            public int format_version = 1;
            public string source_guid, target_guid, source_account, target_account;
            public int type;
            public double expires_at;
        }
        [Serializable] private sealed class ChatGrant
        { public int format_version = 1; public string a, b; public double expires_at; }
        private sealed class FriendshipOverlay
        { public Actor A, B; public bool Friends; public double Expires; }
        private sealed class RelationOverlay
        { public string Key; public bool Enabled; public double Expires; }

        private readonly string directory;
        private readonly Func<double> clock;
        private readonly HashSet<string> relations = new HashSet<string>(StringComparer.Ordinal);
        private readonly Dictionary<string, FriendshipOverlay> overlays = new Dictionary<string, FriendshipOverlay>(StringComparer.Ordinal);
        private readonly Dictionary<string, RelationOverlay> relationOverlays = new Dictionary<string, RelationOverlay>(StringComparer.Ordinal);
        private long snapshotStamp = -1, snapshotLength = -1;
        private const double RelationOverlaySeconds = 15;

        public NebulaSocialState(string stateDirectory, Func<double> clock = null)
        {
            directory = stateDirectory;
            this.clock = clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0);
        }
        private static string RelationKey(Actor a, Actor b, string kind) =>
            a.AccountId + "\0" + b.Username + "\0" + b.Platform + "\0" + kind;
        private static string Pair(string a, string b) => String.CompareOrdinal(a, b) < 0 ? a + "\0" + b : b + "\0" + a;
        private static string Digest(string key)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(key))).Replace("-", "").ToLowerInvariant();
        }
        private string PendingPath(Actor source, Actor target, int type) => Path.Combine(directory, "social-requests",
            Digest(source.Guid + "\0" + target.Guid + "\0" + type) + ".json");
        private string GrantPath(Actor a, Actor b) => Path.Combine(directory, "social-chat-grants", Digest(Pair(a.Guid, b.Guid)) + ".json");
        private double Now() => clock();
        private static T Read<T>(string path) where T : class
        {
            if (!File.Exists(path) || new FileInfo(path).Length > 8192) return null;
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(stream, new UTF8Encoding(false, true)))
                return JsonUtility.FromJson<T>(reader.ReadToEnd());
        }
        private static void WriteNew<T>(string path, T value)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string temporary = path + "." + System.Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (var writer = new StreamWriter(stream, new UTF8Encoding(false))) writer.Write(JsonUtility.ToJson(value));
                File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        private void Refresh()
        {
            string path = Path.Combine(directory, "instance-relations.json");
            var info = new FileInfo(path);
            if (!info.Exists)
            {
                relations.Clear(); snapshotStamp = -1; snapshotLength = -1;
                RetireFriendshipOverlays();
                RetireRelationOverlays();
                return;
            }
            if (info.LastWriteTimeUtc.Ticks == snapshotStamp && info.Length == snapshotLength)
            {
                RetireFriendshipOverlays();
                RetireRelationOverlays();
                return;
            }
            Snapshot snapshot;
            // HTTP replaces this file atomically on Windows; do not hold a
            // reader lock that prevents replacement or deletion.
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(stream, new System.Text.UTF8Encoding(false, true)))
                snapshot = JsonUtility.FromJson<Snapshot>(reader.ReadToEnd());
            var replacement = new HashSet<string>(StringComparer.Ordinal);
            // Missing/unknown versions represent no usable snapshot. Extra
            // fields are intentionally tolerated for forward compatibility.
            if (snapshot != null && snapshot.format_version == 1 && snapshot.relations != null)
                foreach (RelationRow row in snapshot.relations)
                {
                    if (row == null || String.IsNullOrEmpty(row.ps4_id) || String.IsNullOrEmpty(row.target) ||
                        (row.target_platform != "PS4" && row.target_platform != "StandaloneWindows") ||
                        (row.kind != "friend" && row.kind != "favorite" && row.kind != "block" && row.kind != "silenced")) continue;
                    replacement.Add(row.ps4_id + "\0" + row.target + "\0" + row.target_platform + "\0" + row.kind);
                }
            relations.Clear(); relations.UnionWith(replacement);
            snapshotStamp = info.LastWriteTimeUtc.Ticks; snapshotLength = info.Length;
            RetireFriendshipOverlays();
            RetireRelationOverlays();
        }

        private void RetireFriendshipOverlays()
        {
            double now = Now();
            foreach (var item in overlays.ToArray())
            {
                FriendshipOverlay state = item.Value;
                bool forward = relations.Contains(RelationKey(state.A, state.B, "friend"));
                bool reverse = relations.Contains(RelationKey(state.B, state.A, "friend"));
                if (state.Expires <= now || (state.Friends ? forward && reverse : !forward && !reverse))
                    overlays.Remove(item.Key);
            }
        }

        private void RetireRelationOverlays()
        {
            double now = Now();
            foreach (var item in relationOverlays.ToArray())
                if (item.Value.Expires <= now || relations.Contains(item.Value.Key) == item.Value.Enabled)
                    relationOverlays.Remove(item.Key);
        }

        private bool Has(Actor a, Actor b, string kind)
        {
            string key = RelationKey(a, b, kind);
            if (relationOverlays.TryGetValue(key, out RelationOverlay state))
            {
                if (state.Expires > Now()) return state.Enabled;
                relationOverlays.Remove(key);
            }
            return relations.Contains(key);
        }
        private bool Friends(Actor a, Actor b)
        {
            string key = Pair(a.AccountId, b.AccountId);
            if (overlays.TryGetValue(key, out FriendshipOverlay state))
            {
                if (state.Expires > Now()) return state.Friends;
                overlays.Remove(key);
            }
            return Has(a, b, "friend");
        }

        public int Relation(Actor viewer, Actor target)
        {
            Refresh();
            // Native enum values, with explicit replacement conflict priority.
            if (Has(viewer, target, "block")) return 5;
            if (Has(target, viewer, "block")) return 6;
            if (Has(viewer, target, "silenced")) return 3;
            if (Has(target, viewer, "silenced")) return 4;
            if (Has(viewer, target, "favorite")) return 2;
            return Friends(viewer, target) ? 1 : 0;
        }

        public NebulaSocialRelationSnapshot.State RelationSnapshot(Actor viewer, Actor target)
        {
            Refresh();
            return new NebulaSocialRelationSnapshot.State(
                friend: Friends(viewer, target), favorite: Has(viewer, target, "favorite"),
                ignored: Has(viewer, target, "silenced"), silentBy: Has(target, viewer, "silenced"),
                blockedUsers: Has(viewer, target, "block"), userBlockedBy: Has(target, viewer, "block"));
        }

        public bool CanReceive(Actor recipient, Actor sender)
        {
            Refresh();
            return recipient.AccountId == sender.AccountId ||
                (!Has(recipient, sender, "block") && !Has(sender, recipient, "block") && !Has(recipient, sender, "silenced"));
        }

        public bool CanPrivateChat(Actor a, Actor b)
        {
            Refresh();
            ChatGrant grant = Read<ChatGrant>(GrantPath(a, b));
            bool consent = grant != null && grant.format_version == 1 && grant.expires_at > Now() &&
                Pair(grant.a ?? "", grant.b ?? "") == Pair(a.Guid, b.Guid);
            return CanReceive(a, b) && CanReceive(b, a) &&
                (Friends(a, b) || Friends(b, a) || consent);
        }

        public void Request(Actor source, Actor target, int type)
        {
            Expire();
            if (source.AccountId == target.AccountId) throw new Rejected("notification_to_self");
            if (type != 0 && type != 1 && type != 6) throw new Rejected("unsupported_notification_type");
            if (!CanReceive(target, source)) throw new Rejected("notification_relation_denied");
            string path = PendingPath(source, target, type);
            if (File.Exists(path)) throw new Rejected("notification_already_pending");
            string folder = Path.GetDirectoryName(path);
            if (Directory.Exists(folder) && Directory.EnumerateFiles(folder, "*.json").Take(257).Count() >= 256)
                throw new Rejected("notification_capacity");
            WriteNew(path, new Pending {source_guid = source.Guid, target_guid = target.Guid,
                source_account = source.AccountId, target_account = target.AccountId, type = type, expires_at = Now() + 300});
        }

        public void Accept(Actor acceptor, Actor requester, int type)
        {
            Expire();
            // Invite6 is accepted by the native HTTP LoadSpace branch, not26.
            // FullGame2 and SpaceGame11 require unimplemented game metadata.
            if (type != 0 && type != 1) throw new Rejected("unsupported_notification_acceptance");
            string path = PendingPath(requester, acceptor, type);
            Pending request = Read<Pending>(path);
            if (request == null || request.format_version != 1 || request.expires_at <= Now() || request.type != type ||
                request.source_guid != requester.Guid || request.target_guid != acceptor.Guid ||
                request.source_account != requester.AccountId || request.target_account != acceptor.AccountId)
                throw new Rejected("uncorrelated_notification_acceptance");
            if (!CanReceive(acceptor, requester) || !CanReceive(requester, acceptor)) throw new Rejected("notification_relation_denied");
            string claim = path + ".claim." + System.Guid.NewGuid().ToString("N");
            try { File.Move(path, claim); }
            catch (IOException) { throw new Rejected("uncorrelated_notification_acceptance"); }
            try
            {
                if (type == 1) WriteFriendEvent(acceptor, requester, true);
                else
                {
                    string grantPath = GrantPath(acceptor, requester);
                    if (File.Exists(grantPath)) File.Delete(grantPath);
                    WriteNew(grantPath, new ChatGrant {a = acceptor.Guid, b = requester.Guid, expires_at = Now() + 86400});
                }
            }
            catch
            {
                if (!File.Exists(path)) File.Move(claim, path);
                throw;
            }
            finally { if (File.Exists(claim)) File.Delete(claim); }
        }

        // Called only after an authenticated same-host accepted relay event.
        // HTTP remains the persistence authority. Never grant indefinite chat
        // authority when its durable event is rejected or lost.
        public void ObserveFriendship(Actor a, Actor b, bool friends = true) =>
            overlays[Pair(a.AccountId, b.AccountId)] = new FriendshipOverlay {
                A = a, B = b, Friends = friends, Expires = Now() + RelationOverlaySeconds};

        // Called only for the authenticated actor's native22..25 callback after
        // the corresponding HTTP mutation succeeded, or its same-host relay.
        // It closes the bounded snapshot-publication gap without becoming a
        // persistence authority or changing friendship/chat consent.
        public void ObserveRelation(Actor owner, Actor target, string kind, bool enabled)
        {
            if (owner == null || target == null || owner.AccountId == target.AccountId ||
                (kind != "block" && kind != "silenced"))
                throw new Rejected("invalid_relation_overlay");
            Refresh();
            string key = RelationKey(owner, target, kind);
            relationOverlays[key] = new RelationOverlay {Key = key, Enabled = enabled, Expires = Now() + RelationOverlaySeconds};
        }

        public void CancelRequest(Actor source, Actor target, int type)
        { File.Delete(PendingPath(source, target, type)); }

        public void RemoveFriendship(Actor actor, Actor other) { WriteFriendEvent(actor, other, false); }

        private void WriteFriendEvent(Actor actor, Actor other, bool friends)
        {
            string eventId = System.Guid.NewGuid().ToString("N");
            var entry = new FriendEvent {
                event_id = eventId, operation = friends ? "accept_friendship" : "remove_friendship",
                actor_ps4_id = actor.AccountId, other_ps4_id = other.AccountId,
                created_at = Now()
            };
            string outbox = Path.Combine(directory, "friend-events");
            Directory.CreateDirectory(outbox);
            string temporary = Path.Combine(outbox, eventId + ".tmp"), path = Path.Combine(outbox, eventId + ".json");
            try
            {
                File.WriteAllText(temporary, JsonUtility.ToJson(entry), new System.Text.UTF8Encoding(false));
                File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
            ObserveFriendship(actor, other, friends);
        }

        public void Decline(Actor actor, Actor requester, int declineType)
        {
            if (declineType != 10 && declineType != 12) throw new Rejected("unsupported_notification_decline_type");
            // No current producer has reconstructed the corresponding2/11
            // invitation arguments. A fabricated decline would imply one did.
            throw new Rejected("uncorrelated_game_notification_decline");
        }

        public void Disconnect(string guid, bool invalidateSession = true)
        {
            // A Mirror disconnect also occurs during native world switching.
            // The same current HTTP session may immediately join another
            // instance, so only an invalidated session loses shared consent.
            CleanShared(invalidateSession ? guid : null);
        }

        public void Expire()
        {
            CleanShared(null);
        }
        private void CleanShared(string disconnectedGuid)
        {
            double now = Now();
            foreach (string subdir in new[] {"social-requests", "social-chat-grants"})
            {
                string folder = Path.Combine(directory, subdir);
                if (!Directory.Exists(folder)) continue;
                foreach (string path in Directory.EnumerateFiles(folder, "*.json").Take(4096))
                    try
                    {
                        bool remove;
                        if (subdir == "social-requests")
                        {
                            Pending p = Read<Pending>(path);
                            remove = p == null || p.format_version != 1 || !(p.expires_at > now) ||
                                (disconnectedGuid != null && (p.source_guid == disconnectedGuid || p.target_guid == disconnectedGuid));
                        }
                        else
                        {
                            ChatGrant p = Read<ChatGrant>(path);
                            remove = p == null || p.format_version != 1 || !(p.expires_at > now) ||
                                (disconnectedGuid != null && (p.a == disconnectedGuid || p.b == disconnectedGuid));
                        }
                        if (remove) File.Delete(path);
                    }
                    catch (IOException) { } // another same-host instance claimed it
            }
        }
    }
}
