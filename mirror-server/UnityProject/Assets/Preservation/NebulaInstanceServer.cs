using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using Mirror;
using UnityEngine;

namespace NebulaPreservation
{
    // Concrete replacement instance; bounded core validation is separate from
    // full readiness/parity. Requires explicit --nebula-instance and scope flags.
    public sealed class NebulaInstanceServer : MonoBehaviour
    {
        [Serializable]
        private sealed class TransformData
        {
            public Vector3 position;
            public Quaternion rotation;
        }

        private sealed class Peer
        {
            public NetworkConnectionToClient connection;
            public uint netId;
            public bool spawned;
            public bool announced;
            public bool inWardrobe;
            public NebulaInstanceAccounts.Account account;
            public Vector3 position = Vector3.zero;
            public Quaternion rotation = Quaternion.identity;
            public Vector3 scale = Vector3.one;
            public float speed;
            public string locomotion = "";
            public string companion = "";
            public long companionRevision, locomotionRevision;
            public NebulaResourceSelections.Request resourcePending;
            public string animationReply;
            public string typingTarget;
            public bool typingPublic;
            public long interactionPendingSeq = Int64.MinValue;
            public string interactionPendingReason;
            public int interactionPendingReasonCount;
            public double positionUpdatedAt;
            public readonly HashSet<uint> visibleEntities = new HashSet<uint>();
            public readonly HashSet<uint> loadedRemotes = new HashSet<uint>();
            public readonly HashSet<uint> wardrobeShown = new HashSet<uint>();
            public readonly Dictionary<string, int> retiredAccounts = new Dictionary<string, int>(StringComparer.Ordinal);
        }
        private sealed class Reseed
        {
            public Peer actor, viewer;
            public NetworkConnectionToClient actorConnection, viewerConnection;
            public string actorGuid, viewerGuid;
            public int earliestFrame;
            public int[] relationCodes;
        }

        [Serializable] private sealed class Pose
        {
            public string ps4_id;
            public Vector3 position;
            public Quaternion rotation = Quaternion.identity;
            public Vector3 scale = Vector3.one;
            public double updated_at;
        }
        [Serializable] private sealed class PoseSnapshot
        { public int format_version = 1; public string instance_id, psidglobal; public double generation; public Pose[] poses; }
        [Serializable] private sealed class AvatarRecord
        {
            public string guid, ps4_id;
            public uint net_id;
            public bool connected, announced, in_wardrobe;
            public Vector3 position, scale;
            public Quaternion rotation;
            public double position_updated_at;
        }
        [Serializable] private sealed class AvatarSnapshot
        {
            public int format_version = 1;
            public string instance_id, psidglobal;
            public double generation;
            public bool listening;
            public string wardrobe_delivery = "mirror_after_avatar_ready_v1";
            public AvatarRecord[] avatars;
        }
        [Serializable] private sealed class ConsumableReceipt
        {
            public int format_version;
            public string policy, receipt_id, guid, ps4_id, kind;
            public int table_id, use_count, reward_index;
            public double issued_at, expires_at;
        }

        [Serializable] private sealed class HousingBinding
        { public string instance_id, psidglobal, owner_ps4_id, logical_space_key; }
        [Serializable] private sealed class HousingBindings
        { public int format_version; public double generation; public HousingBinding[] bindings; }

        [Serializable]
        private sealed class JournalEntry
        {
            public string utc;
            public string kind;
            public int connection;
            public int opcode;
            public string detail;
        }

        [Serializable]
        private sealed class Status
        {
            public int format_version = 1;
            public string state;
            public bool game_ready = false;
            public string networking_parity = "unproven";
            public string instance_id;
            public string psidglobal;
            public string ip = "127.0.0.1";
            public string bind = "127.0.0.1";
            public int port;
            public int maxusers = 32;
            public int players;
            public double heartbeat;
            public bool listening;
            public bool listener_bound;
            public string readiness_scope = "closed";
            public bool core_test_eligible = false;
            public bool protocol_complete = false;
            public bool scene_registry_verified;
            public bool interaction_bridge_required;
            public bool interaction_registry_trusted;
            public bool housing_bound;
            public string housing_owner;
            public string owner;
            public string[] implemented_opcodes;
            public int board_tables;
            public int darts_tables;
        }

        private sealed class Rejected : Exception
        {
            public Rejected(string code) : base(code) { }
        }

        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
        private readonly Dictionary<int, Peer> peers = new Dictionary<int, Peer>();
        private readonly Dictionary<int, string> occupables = new Dictionary<int, string>();
        private readonly Dictionary<string, Peer> wardrobeEntities = new Dictionary<string, Peer>(StringComparer.Ordinal);
        private readonly Dictionary<string, Pose> poses = new Dictionary<string, Pose>(StringComparer.Ordinal);
        private readonly List<Reseed> reseeds = new List<Reseed>();
        private readonly Dictionary<string, NebulaSocialRelationSnapshot.State> relationSnapshots =
            new Dictionary<string, NebulaSocialRelationSnapshot.State>(StringComparer.Ordinal);
        private readonly Dictionary<string, double> interactionRebindDeadlines =
            new Dictionary<string, double>(StringComparer.Ordinal);
        private bool? isDay;
        private NebulaInstanceAccounts accounts;
        private NebulaSocialState social;
        private NebulaSocialMailbox socialMailbox;
        private NebulaMinigameState minigames;
        private NebulaWorldState world;
        private NebulaInteractionRegistry interactionRegistry;
        private readonly NebulaNotificationInbox notificationInbox = new NebulaNotificationInbox();
        private readonly NebulaInformationalNotifications informationalNotifications = new NebulaInformationalNotifications();
        private StreamWriter journal;
        private FileStream instanceLock;
        private NebulaResourceSelections resourceSelections;
        private string stateDirectory;
        private string instanceDirectory;
        private string instanceId;
        private string spaceId;
        private readonly string statusOwner = Guid.NewGuid().ToString("N");
        private ushort port;
        private IPAddress bindAddress = IPAddress.Loopback;
        private string advertisedAddress = "127.0.0.1";
        private string coreTestProfile;
        private float nextSocialPump;
        private float nextAuthorizationPump;
        private float nextInteractionPump;
        private string interactionSnapshotIdentity;
        private TelepathyTransport instanceTransport;
        private uint nextNetId = 1;
        private bool started;
        private bool publishedStatus;
        private float nextHeartbeat;
        private bool SemanticBridgeRequired => coreTestProfile == "nonmini-semantic-v1";

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Bootstrap()
        {
#if !UNITY_EDITOR
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "--nebula-instance") < 0) return;
            var host = new GameObject("Nebula preservation core instance");
            DontDestroyOnLoad(host);
            host.AddComponent<NebulaInstanceServer>();
#endif
        }

        private void Start()
        {
            string[] args = Environment.GetCommandLineArgs();
            if (Array.IndexOf(args, "--nebula-instance") < 0) return;
            try
            {
                if (Array.IndexOf(args, "--nebula-listen") >= 0) throw new Rejected("choose_probe_or_instance");
                string directory = Argument(args, "--nebula-state-dir", true);
                stateDirectory = Path.GetFullPath(directory);
                Directory.CreateDirectory(stateDirectory);
                instanceId = Argument(args, "--nebula-instance-id", false) ?? "local-nexus";
                spaceId = Argument(args, "--nebula-space", false) ?? "Nexus";
                if (String.IsNullOrEmpty(instanceId) || instanceId.Length > 128 || instanceId.Any(c =>
                        !((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-')) ||
                    String.IsNullOrEmpty(spaceId) || spaceId.Length > 128 || spaceId.Contains("#"))
                    throw new Rejected("invalid_instance_or_space_identifier");
                instanceDirectory = Path.Combine(stateDirectory, "instances", instanceId);
                Directory.CreateDirectory(instanceDirectory);
                instanceLock = new FileStream(Path.Combine(instanceDirectory, "instance.lock"),
                    FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
                string portText = Argument(args, "--nebula-port", false) ?? "28000";
                if (!UInt16.TryParse(portText, NumberStyles.None, Invariant, out port) || port == 0)
                    throw new Rejected("invalid_port");
                bindAddress = IPv4Address(Argument(args, "--nebula-bind", false) ?? "127.0.0.1", true);
                advertisedAddress = IPv4Address(Argument(args, "--nebula-advertise-ip", false) ?? "127.0.0.1", false).ToString();
                coreTestProfile = Argument(args, "--nebula-core-test-profile", false);
                int boardTables = TableCount(args, "--nebula-board-tables");
                int dartsTables = TableCount(args, "--nebula-darts-tables");
                if (coreTestProfile != null && ((coreTestProfile != "nexus-core-v1" && coreTestProfile != "nonmini-core-v1" &&
                        coreTestProfile != "nonmini-semantic-v1") ||
                    (coreTestProfile == "nexus-core-v1" && spaceId != "Nexus") ||
                    (coreTestProfile == "nonmini-core-v1" && !NebulaCoreReadiness.IsNonMiniScene(spaceId)) ||
                    (coreTestProfile == "nonmini-semantic-v1" && !NebulaCoreReadiness.IsSemanticNonMiniScene(spaceId)) ||
                    boardTables != 0 || dartsTables != 0))
                    throw new Rejected("invalid_core_test_profile_or_scene");
                accounts = new NebulaInstanceAccounts(stateDirectory);
                resourceSelections = new NebulaResourceSelections(stateDirectory, instanceId, statusOwner);
                LoadPoses();
                RecoverWardrobe();
                social = new NebulaSocialState(stateDirectory);
                socialMailbox = new NebulaSocialMailbox(stateDirectory, instanceId,
                    entry => JsonUtility.ToJson(entry), text => JsonUtility.FromJson<NebulaSocialMailbox.Envelope>(text));
                // Nexus has no Board/Darts tables. Other scenes must supply
                // their source-backed counts explicitly; zero disables them.
                minigames = new NebulaMinigameState(boardTables, dartsTables, ResolveMinigameIdentity);
                world = new NebulaWorldState(NebulaWorldState.SceneInventory.ForSpace(spaceId), ResolveWorldIdentity,
                    (actor, kind, receipt) => ClaimConsumable(actor.Guid, actor.PlatformId, kind, receipt));
                interactionRegistry = new NebulaInteractionRegistry(instanceId, spaceId, Now);
                RefreshInteractionTrust();
                Directory.CreateDirectory(Path.Combine(instanceDirectory, "instance-logs"));
                string logPath = Path.Combine(instanceDirectory, "instance-logs", "instance-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss", Invariant) + ".jsonl");
                journal = new StreamWriter(logPath, true, new System.Text.UTF8Encoding(false)) { AutoFlush = true };
                if (NetworkServer.active) throw new Rejected("another_network_server_is_active");
                Writer<NebulaMessage>.write = (writer, value) => writer.WriteString(value.data);
                Reader<NebulaMessage>.read = reader => new NebulaMessage { data = reader.ReadString() };
                var transport = gameObject.AddComponent<TelepathyTransport>();
                instanceTransport = transport;
                transport.port = port;
                Telepathy.Server.BindAddress = bindAddress;
                Transport.activeTransport = transport;
                NetworkServer.OnConnectedEvent += Connected;
                NetworkServer.OnDisconnectedEvent += Disconnected;
                NetworkServer.Listen(32);
                started = true;
                // Listen installs Mirror default handlers first. The custom
                // player stream deliberately has no server-side game prefab.
                NetworkServer.RegisterHandler<AddPlayerMessage>(AddPlayer);
                NetworkServer.ReplaceHandler<CommandMessage>(Command, true);
                NetworkServer.RegisterHandler<NebulaMessage>(Message, false);
                Application.runInBackground = true;
                Application.targetFrameRate = 30;
                PublishStatus(true);
                nextHeartbeat = Time.unscaledTime + 5;
                Record("transport_start_requested", null, -1, "core_reconstruction_unvalidated");
                Debug.Log("Nebula core instance IPv4 listener configured; game_ready=false, parity unproven.");
            }
            catch (Exception error)
            {
                // Do not put account/snapshot values or session IDs in stdout.
                Debug.LogError("Nebula instance configuration failed: " + error.GetType().Name);
                Stop();
                Application.Quit(2);
            }
        }

        private void Update()
        {
            if (!started) return;
            if (Time.unscaledTime >= nextAuthorizationPump)
            {
                nextAuthorizationPump = Time.unscaledTime + 0.25f;
                PumpAuthorizations();
            }
            ProcessReseeds();
            PumpResourceSelections();
            if (Time.unscaledTime >= nextSocialPump)
            {
                nextSocialPump = Time.unscaledTime + 0.25f;
                socialMailbox.Drain(Now(), DeliverSocialRelay, code => Record("rejected", null, -1, code));
            }
            if (Time.unscaledTime >= nextInteractionPump)
            {
                nextInteractionPump = Time.unscaledTime + 0.5f;
                RefreshInteractionTrust();
            }
            if (Time.unscaledTime < nextHeartbeat) return;
            nextHeartbeat = Time.unscaledTime + 5;
            social.Expire();
            informationalNotifications.Expire(Now());
            ReconcileSessions();
            PumpNotifications();
            TryPublishStatus(true);
        }

        private void PumpNotifications()
        {
            string path = Path.Combine(stateDirectory, "instance-notifications.json");
            if (!File.Exists(path)) return;
            try
            {
                if (new FileInfo(path).Length > 16 * 1024 * 1024)
                    throw new Rejected("notification_snapshot_too_large");
                string text;
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var reader = new StreamReader(stream, new System.Text.UTF8Encoding(false, true))) text = reader.ReadToEnd();
                double now = Now();
                notificationInbox.Replace(JsonUtility.FromJson<NebulaNotificationInbox.Snapshot>(text), now);
                // C2S1 is sent after the native local avatar callback. Earlier
                // transport spawn alone is not a notification UI readiness signal.
                foreach (Peer peer in peers.Values.Where(x => x.announced && x.spawned && x.account != null).ToArray())
                {
                    Bound(peer);
                    foreach (NebulaNotificationInbox.Delivery delivery in notificationInbox.Peek(peer.account.ps4_id, peer.account.guid, now))
                    {
                        Send(peer, delivery.Payload);
                        notificationInbox.MarkQueued(delivery);
                    }
                }
            }
            catch (Exception error)
            {
                Record("notification_refresh_rejected", null, 19, error.GetType().Name);
            }
        }

        private NebulaNotificationInbox.Acknowledgement PersistNotificationAcknowledgement(NebulaNotificationInbox.Acknowledgement ack)
        {
            string directory = Path.Combine(stateDirectory, "notification-acks");
            Directory.CreateDirectory(directory);
            // Session-qualified immutable files permit a new current session
            // to acknowledge a replay even if an old receipt was never imported.
            string path = Path.Combine(directory, ack.event_id + "-" + ack.guid + ".json");
            string temporary = Path.Combine(directory, ack.event_id + "-" + ack.guid + "-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (var writer = new StreamWriter(stream, new System.Text.UTF8Encoding(false)))
                    writer.Write(JsonUtility.ToJson(ack));
                try { File.Move(temporary, path); }
                catch (IOException) { if (!File.Exists(path)) throw; }
                string text;
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var reader = new StreamReader(stream, new System.Text.UTF8Encoding(false, true))) text = reader.ReadToEnd();
                var existing = JsonUtility.FromJson<NebulaNotificationInbox.Acknowledgement>(text);
                if (existing == null || existing.format_version != 1 || existing.event_id != ack.event_id ||
                    existing.guid != ack.guid || existing.target_ps4_id != ack.target_ps4_id ||
                    existing.source_username != ack.source_username || existing.source_platform != ack.source_platform ||
                    existing.notification_type != ack.notification_type || Double.IsNaN(existing.accepted_at) ||
                    Double.IsInfinity(existing.accepted_at) || existing.accepted_at < 0 || existing.accepted_at > Now() + 30)
                    throw new Rejected("conflicting_notification_acknowledgement");
                return existing;
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        private static int TableCount(string[] args, string key)
        {
            string text = Argument(args, key, false);
            if (text == null) return 0;
            int count = Integer(text);
            if (count < 0 || count > 64) throw new Rejected("invalid_scene_table_count");
            return count;
        }

        private static string Argument(string[] args, string key, bool required)
        {
            int at = Array.IndexOf(args, key);
            if (at < 0)
            {
                if (required) throw new Rejected("missing_argument");
                return null;
            }
            if (at + 1 >= args.Length || args[at + 1].StartsWith("--", StringComparison.Ordinal))
                throw new Rejected("missing_argument_value");
            return args[at + 1];
        }

        private static IPAddress IPv4Address(string text, bool wildcard)
        {
            string[] parts = text.Split('.');
            if (parts.Length != 4) throw new Rejected("invalid_ipv4_address");
            var bytes = new byte[4];
            for (int index = 0; index < bytes.Length; ++index)
            {
                string part = parts[index];
                if (part.Length == 0 || part.Length > 3 || (part.Length > 1 && part[0] == '0') ||
                    part.Any(c => c < '0' || c > '9') || !Byte.TryParse(part, NumberStyles.None, Invariant, out bytes[index]))
                    throw new Rejected("invalid_ipv4_address");
            }
            if (bytes[0] >= 224 || (bytes[0] == 0 && !(wildcard && bytes.All(x => x == 0))))
                throw new Rejected("invalid_ipv4_address");
            return new IPAddress(bytes);
        }

        private static double Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;

        private IEnumerable<Peer> Entities() => peers.Values.Where(x => x.announced && x.account != null)
            .Concat(wardrobeEntities.Values);

        private bool WardrobeLease(NebulaInstanceAccounts.Account account)
        {
            double age = Now() - account.wardrobe_updated_at;
            return account.wardrobe_active && account.wardrobe_instance_id == instanceId && age >= 0 && age <= 60;
        }

        private void RestorePose(Peer peer)
        {
            if (poses.TryGetValue(peer.account.ps4_id, out Pose pose))
            {
                peer.position = pose.position; peer.rotation = pose.rotation;
                peer.scale = pose.scale; peer.positionUpdatedAt = pose.updated_at;
            }
            if (peer.account.position_updated_at > peer.positionUpdatedAt)
            {
                peer.position = peer.account.position;
                peer.positionUpdatedAt = peer.account.position_updated_at;
            }
        }

        private void RememberPose(Peer peer)
        {
            if (peer.account == null || peer.positionUpdatedAt <= 0) return;
            if (poses.TryGetValue(peer.account.ps4_id, out Pose previous) && previous.updated_at > peer.positionUpdatedAt) return;
            poses[peer.account.ps4_id] = new Pose {ps4_id = peer.account.ps4_id, position = peer.position,
                rotation = peer.rotation, scale = peer.scale, updated_at = peer.positionUpdatedAt};
        }

        private void ObservePose(Peer peer)
        {
            peer.positionUpdatedAt = Now();
            RememberPose(peer);
        }

        private void LoadPoses()
        {
            string path = Path.Combine(instanceDirectory, "instance-poses.json");
            if (!File.Exists(path)) return;
            try
            {
                PoseSnapshot snapshot;
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var reader = new StreamReader(stream)) snapshot = JsonUtility.FromJson<PoseSnapshot>(reader.ReadToEnd());
                if (snapshot == null || snapshot.format_version != 1 || snapshot.instance_id != instanceId ||
                    snapshot.psidglobal != spaceId || snapshot.poses == null) return;
                foreach (Pose value in snapshot.poses)
                {
                    if (value == null || String.IsNullOrEmpty(value.ps4_id) || value.ps4_id.Length > 128 ||
                        !Finite(value.position) || !Finite(value.rotation) || !Finite(value.scale) ||
                        Double.IsNaN(value.updated_at) || Double.IsInfinity(value.updated_at) || value.updated_at <= 0 ||
                        value.updated_at > Now() + 5 || poses.ContainsKey(value.ps4_id)) continue;
                    double norm = (double)value.rotation.x * value.rotation.x + (double)value.rotation.y * value.rotation.y +
                        (double)value.rotation.z * value.rotation.z + (double)value.rotation.w * value.rotation.w;
                    if (norm < 0.000001) continue;
                    poses.Add(value.ps4_id, value);
                }
            }
            catch (Exception error) when (error is IOException || error is ArgumentException || error is UnauthorizedAccessException)
            { poses.Clear(); }
        }

        private void RecoverWardrobe()
        {
            foreach (NebulaInstanceAccounts.Account account in accounts.All().OrderBy(x => x.guid, StringComparer.Ordinal))
            {
                if (!WardrobeLease(account) || account.allocated_instance_id != instanceId || wardrobeEntities.ContainsKey(account.ps4_id) ||
                    peers.Values.Any(x => x.account != null && x.account.ps4_id == account.ps4_id)) continue;
                var entity = new Peer {account = account, netId = nextNetId++, spawned = true, announced = true, inWardrobe = true, companion = account.selected_companion, locomotion = account.selected_locomotion, companionRevision = account.companion_revision, locomotionRevision = account.locomotion_revision};
                RestorePose(entity);
                wardrobeEntities.Add(account.ps4_id, entity);
            }
        }

        private void SeedRemotes(Peer recipient)
        {
            foreach (Peer entity in Entities().Where(x => x != recipient && x.account.ps4_id != recipient.account.ps4_id).OrderBy(x => x.netId))
                SeedRemote(entity, recipient);
        }

        private void SeedRemote(Peer actor, Peer viewer)
        {
            if (viewer.visibleEntities.Contains(actor.netId) || reseeds.Any(x => x.actor == actor && x.viewer == viewer)) return;
            if (viewer.retiredAccounts.TryGetValue(actor.account.ps4_id, out int earliestFrame) && Time.frameCount < earliestFrame)
            {
                QueueReseed(actor, viewer, earliestFrame);
                return;
            }
            viewer.retiredAccounts.Remove(actor.account.ps4_id);
            Spawn(actor, viewer, false);
            Send(viewer, JoinedReply(actor));
        }

        private void RetireEntity(Peer entity)
        {
            reseeds.RemoveAll(x => x.actor == entity);
            foreach (Peer recipient in peers.Values.Where(x => x.spawned).ToArray())
                RetireEntityFor(entity, recipient);
        }

        private static bool RetireEntityFor(Peer entity, Peer recipient)
        {
            recipient.loadedRemotes.Remove(entity.netId);
            recipient.wardrobeShown.Remove(entity.netId);
            if (!recipient.visibleEntities.Remove(entity.netId)) return false;
            recipient.retiredAccounts[entity.account.ps4_id] = Time.frameCount + 2;
            Send(recipient, Join(14, entity.account.guid));
            recipient.connection.Send(new ObjectDestroyMessage {netId = entity.netId});
            return true;
        }

        private void RefreshVehicleExit(Peer actor)
        {
            actor.animationReply = null;
            foreach (Peer viewer in peers.Values.Where(x => x != actor && x.spawned && x.account != null &&
                x.loadedRemotes.Contains(actor.netId)).ToArray())
            {
                if (!RetireEntityFor(actor, viewer)) continue;
                QueueReseed(actor, viewer, Time.frameCount + 2);
            }
        }

        private void QueueReseed(Peer actor, Peer viewer, int earliestFrame, int[] relationCodes = null)
        {
            if (reseeds.Any(x => x.actor == actor && x.viewer == viewer)) return;
            reseeds.Add(new Reseed {actor = actor, viewer = viewer, actorConnection = actor.connection,
                viewerConnection = viewer.connection, actorGuid = actor.account.guid, viewerGuid = viewer.account.guid,
                earliestFrame = earliestFrame, relationCodes = relationCodes});
        }

        private void ProcessReseeds()
        {
            foreach (Reseed item in reseeds.Where(x => Time.frameCount >= x.earliestFrame).ToArray())
            {
                if (item.actor.connection != item.actorConnection || item.viewer.connection != item.viewerConnection ||
                    item.viewer.connection == null ||
                    !peers.TryGetValue(item.viewerConnection.connectionId, out Peer viewer) || viewer != item.viewer ||
                    item.actor.account == null || viewer.account == null || item.actor.account.guid != item.actorGuid ||
                    viewer.account.guid != item.viewerGuid)
                { reseeds.Remove(item); continue; }
                Peer actor = item.actor;
                bool currentActor = actor.connection != null
                    ? peers.TryGetValue(actor.connection.connectionId, out Peer active) && active == actor
                    : wardrobeEntities.TryGetValue(actor.account.ps4_id, out Peer retained) && retained == actor;
                if (!currentActor) { reseeds.Remove(item); continue; }
                if (!actor.announced) continue;
                if (viewer.retiredAccounts.TryGetValue(actor.account.ps4_id, out int earliestFrame) && Time.frameCount < earliestFrame)
                { item.earliestFrame = earliestFrame; continue; }
                reseeds.Remove(item);
                try
                {
                    Bound(viewer);
                    if (actor.connection != null) Bound(actor);
                    else
                    {
                        NebulaInstanceAccounts.Account current = accounts.Find(actor.account.guid);
                        if (current == null || current.ps4_id != actor.account.ps4_id || current.platform != actor.account.platform ||
                            current.allocated_instance_id != instanceId || !WardrobeLease(current))
                            throw new Rejected("retained_wardrobe_session_not_current");
                        actor.account = current;
                    }
                    viewer.retiredAccounts.Remove(actor.account.ps4_id);
                    Spawn(actor, viewer, false);
                    Send(viewer, JoinedReply(actor));
                    if (item.relationCodes != null)
                        foreach (int code in item.relationCodes) Send(viewer, Join(28, actor.account.guid, code.ToString(Invariant)));
                }
                catch (Rejected error) { Record("reseed_cancelled", viewer.connection, 31, error.Message); }
                catch (Exception) { Record("reseed_cancelled", viewer.connection, 31, "invalid_current_snapshot"); }
            }
        }

        private void ShowWardrobe(Peer entity, Peer recipient)
        {
            if (!entity.inWardrobe || recipient.account == null || !recipient.loadedRemotes.Contains(entity.netId) ||
                !recipient.visibleEntities.Contains(entity.netId) || !recipient.wardrobeShown.Add(entity.netId)) return;
            Send(recipient, Join(29, entity.account.guid));
        }

        private void EnterWardrobe(Peer peer, string[] fields, string platform)
        {
            Count(fields, 1); Own(peer, fields[0], platform); RequireAnnounced(peer);
            if (peer.inWardrobe) return;
            if (!WardrobeLease(peer.account)) throw new Rejected("wardrobe_requires_fresh_http_lease");
            // The native HTTP request captures position immediately before29.
            // Prefer it to an older movement sample for the editing ghost.
            if (peer.account.position_updated_at > peer.positionUpdatedAt)
            { peer.position = peer.account.position; peer.positionUpdatedAt = peer.account.position_updated_at; }
            RememberPose(peer);
            StopTyping(peer);
            peer.inWardrobe = true;
            Send(peer, Join(29, peer.account.guid));
            foreach (Peer recipient in peers.Values.Where(x => x != peer && x.spawned)) ShowWardrobe(peer, recipient);
            TryPublishStatus(true);
        }

        private bool PumpAuthorizations()
        {
            try
            {
                ReconcileAuthorizations();
                return true;
            }
            catch (Exception error)
            {
                Record("authorization_refresh_rejected", null, -1, error.GetType().Name);
                // A cached/malformed authority never keeps idle sessions alive.
                // Disconnect only this instance's actual bound connections.
                foreach (Peer peer in peers.Values.Where(x => x.account != null).ToArray()) DisconnectAuthorization(peer);
                foreach (var item in wardrobeEntities.ToArray())
                {
                    wardrobeEntities.Remove(item.Key);
                    try { RetireEntity(item.Value); } catch (Exception) { }
                }
                return false;
            }
        }

        private void DisconnectAuthorization(Peer peer)
        {
            NetworkConnectionToClient connection = peer.connection;
            if (connection == null) return;
            try { Disconnected(connection); }
            catch (Exception error) { Record("authorization_cleanup_rejected", connection, -1, error.GetType().Name); }
            finally
            {
                try { connection.Disconnect(); }
                catch (Exception error) { Record("authorization_disconnect_rejected", connection, -1, error.GetType().Name); }
            }
        }

        private void ReconcileAuthorizations()
        {
            // Force freshness even with zero bound peers/retained entities.
            accounts.All();
            foreach (Peer peer in peers.Values.Where(x => x.account != null).ToArray())
            {
                NebulaInstanceAccounts.Account current = accounts.Find(peer.account.guid);
                if (current == null || current.ps4_id != peer.account.ps4_id || current.platform != peer.account.platform ||
                    current.allocated_instance_id != instanceId || (peer.inWardrobe && !WardrobeLease(current)))
                {
                    DisconnectAuthorization(peer);
                }
                else
                {
                    peer.account = current;
                    if (current.ChatMuted(Now()) && (peer.typingPublic || peer.typingTarget != null)) StopTyping(peer);
                }
            }
            foreach (var item in wardrobeEntities.ToArray())
            {
                Peer entity = item.Value;
                NebulaInstanceAccounts.Account current = accounts.Find(entity.account.guid);
                if (current == null || current.ps4_id != entity.account.ps4_id || current.allocated_instance_id != instanceId || !WardrobeLease(current))
                {
                    wardrobeEntities.Remove(item.Key);
                    RetireEntity(entity);
                }
                else entity.account = current;
            }
        }

        private void ReconcileSessions()
        {
            if (!PumpAuthorizations()) return;
            RecoverWardrobe();
            foreach (Peer recipient in peers.Values.Where(x => x.account != null && x.spawned).ToArray()) SeedRemotes(recipient);
        }

        private void Connected(NetworkConnectionToClient connection)
        {
            // Transport-level authentication admits ready/add-player only.
            // Every account-affecting custom command separately binds a GUID.
            connection.isAuthenticated = true;
            peers.Add(connection.connectionId, new Peer { connection = connection });
            Record("connected", connection, -1, "transport_only");
            TryPublishStatus(true);
        }

        private void AddPlayer(NetworkConnectionToClient connection, AddPlayerMessage _)
        {
            if (!peers.TryGetValue(connection.connectionId, out Peer peer) || peer.connection != connection || peer.spawned || !connection.isReady)
            {
                Record("rejected", connection, -1, "invalid_add_player_state");
                return;
            }
            peer.netId = nextNetId++;
            if (peer.netId == 0)
            {
                connection.Disconnect();
                return;
            }
            peer.spawned = true;
            connection.Send(new ObjectSpawnStartedMessage());
            Spawn(peer, peer, true);
            connection.Send(new ObjectSpawnFinishedMessage());
            // Remote entities wait for a GUID-bearing application request.
            // AddPlayer carries no account identity, so eagerly seeding a
            // retained wardrobe actor could spawn this client's own old GUID.
            Send(peer, "0");
            Record("local_spawn", connection, 0, "awaiting_application_identity");
        }

        private static void Spawn(Peer entity, Peer recipient, bool local)
        {
            if (!recipient.visibleEntities.Add(entity.netId)) return;
            byte[] state = NebulaSpawnState.Initial(entity.position, entity.rotation, entity.speed);
            recipient.connection.Send(new SpawnMessage {
                netId = entity.netId, isLocalPlayer = local, isOwner = local,
                sceneId = 0, assetId = NebulaSpawnState.PlayerAssetId,
                position = entity.position, rotation = entity.rotation, scale = entity.scale,
                payload = new ArraySegment<byte>(state)
            });
        }

        private void Message(NetworkConnectionToClient connection, NebulaMessage message, int channel)
        {
            int opcode = -1;
            bool dispatched = false;
            if (!peers.TryGetValue(connection.connectionId, out Peer peer) || peer.connection != connection) return;
            try
            {
                if (!peer.spawned) throw new Rejected("application_before_spawn");
                string plaintext = NebulaApplicationCrypto.DecryptClient(message.data);
                string[] tokens = plaintext.Split(new[] {'#'}, StringSplitOptions.None);
                if (tokens.Length < 2 || !Int32.TryParse(tokens[0], NumberStyles.Integer, Invariant, out opcode))
                    throw new Rejected("invalid_opcode");
                string platform = tokens[tokens.Length - 1];
                if (platform != "PS4" && platform != "StandaloneWindows") throw new Rejected("invalid_platform_trailer");
                if (peer.account != null && platform != peer.account.platform) throw new Rejected("platform_mismatch");
                string[] fields = tokens.Skip(1).Take(tokens.Length - 2).ToArray();
                Dispatch(peer, opcode, fields, platform);
                dispatched = true;
            }
            catch (Rejected error)
            {
                Record("rejected", connection, opcode, error.Message);
            }
            catch (NebulaSocialState.Rejected error)
            {
                Record("rejected", connection, opcode, error.Code);
            }
            catch (NebulaMinigameState.Rejected error)
            {
                Record("rejected", connection, opcode, error.Code);
            }
            catch (NebulaWorldState.Rejected error)
            {
                Record("rejected", connection, opcode, error.Code);
            }
            catch (NebulaInteractionRegistry.Rejected error)
            {
                Record("rejected", connection, opcode, error.Code);
            }
            catch (Exception)
            {
                // Cipher, snapshot, JSON and numeric failures are metadata-only.
                Record("rejected", connection, opcode, "invalid_packet_or_snapshot");
            }
            finally
            {
                // Native seats animate before any opcode-9 acceptance. No
                // source-proven rollback exists for conflict, pending, stale,
                // malformed, or otherwise rejected semantic claims.
                if (!dispatched && peer.account != null && interactionRegistry != null &&
                    interactionRegistry.RequiresReloadAfterRejectedClaim(peer.account.guid, opcode))
                    connection.Disconnect();
            }
        }

        private void Dispatch(Peer peer, int opcode, string[] f, string platform)
        {
            if (opcode == 97) { InteractionRegistry(peer, f, platform); return; }
            if (opcode == 8 || opcode == 9 || opcode == 10 || opcode == 94)
            {
                if (f.Length == 0) throw new Rejected("missing_world_identity");
                Own(peer, f[0], platform);
                if (SemanticBridgeRequired) interactionRegistry.Require(peer.account.guid);
                if (interactionRegistry.IsOptedIn(peer.account.guid))
                {
                    if (peer.inWardrobe) throw new Rejected("world_interaction_while_in_wardrobe");
                    DeliverInteractions(interactionRegistry.Handle(peer.account.guid, opcode, f, InteractionReadyGuids()));
                    return;
                }
            }
            if (world.Handles(opcode))
            {
                if (f.Length == 0) throw new Rejected("missing_world_identity");
                Own(peer, f[0], platform);
                if (peer.inWardrobe) throw new Rejected("world_interaction_while_in_wardrobe");
                bool hadBoat = opcode == 31 && world.HasBoat(peer.account.guid);
                DeliverWorld(world.Handle(peer.account.guid, opcode, f), peer);
                if (hadBoat && !world.HasBoat(peer.account.guid)) RefreshVehicleExit(peer);
                return;
            }
            if (minigames.Handles(opcode))
            {
                if (f.Length == 0) throw new Rejected("missing_minigame_identity");
                Own(peer, f[0], platform);
                if (opcode == 32 && (f.Length < 2 || f[1] != peer.account.ps4_id))
                    throw new Rejected("minigame_account_mismatch");
                DeliverMinigame(minigames.Handle(peer.account.guid, opcode, f));
                return;
            }
            switch (opcode)
            {
                case 1: Announce(peer, f, platform); return;
                case 2: Transform(peer, f); return;
                case 3: Query(peer, f, platform, 5); return;
                case 4: Animation(peer, f, platform); return;
                case 6: Query(peer, f, platform, 17); return;
                case 8: Occupancy(peer, f, platform, false); return;
                case 9: Occupancy(peer, f, platform, true); return;
                case 10: LeaveOccupancy(peer, f, platform); return;
                case 11: StartTyping(peer, f, platform); return;
                case 12: Count(f, 1); Own(peer, f[0], platform); StopTyping(peer); return;
                case 13: Chat(peer, f, platform); return;
                case 15:
                    Count(f, 2); Own(peer, f[0], platform);
                    BeginResourceSelection(peer, "locomotions", f[1]); return;
                case 16: Query(peer, f, platform, 15); return;
                case 17:
                    Count(f, 2); Own(peer, f[0], platform);
                    BeginResourceSelection(peer, "companions", f[1]); return;
                case 18: Preference(peer, f, platform); return;
                case 19: Notification(peer, f); return;
                case 20: Query(peer, f, platform, 2); return;
                case 21: case 22: case 23: case 24: case 25:
                    SocialRefresh(peer, opcode, f, platform); return;
                case 26: AcceptNotification(peer, f, platform); return;
                case 29:
                    EnterWardrobe(peer, f, platform); return;
                case 30:
                    Count(f, 1); Bound(peer); bool day = BooleanValue(f[0]);
                    isDay = day;
                    Broadcast("30##" + (day ? "True" : "False"), null); return;
                case 92: AnimationParameter(peer, f, platform); return;
                case 95: DeclineNotification(peer, f, platform); return;
                default:
                    Record("unsupported_opcode", peer.connection, opcode, "no_reconstructed_transition"); return;
            }
        }

        private void Announce(Peer peer, string[] f, string platform)
        {
            Count(f, 4);
            if (Unsigned(f[0]) != peer.netId) throw new Rejected("netid_not_owned");
            Own(peer, f[1], platform);
            if (f[2] != peer.account.username || Integer(f[3]) != peer.account.PlatformNumber)
                throw new Rejected("identity_claim_mismatch");
            if (peer.announced) return;
            try
            {
                // Also inform clients still assembling their local avatar. Two
                // concurrent joins can both have spawned before either announces.
                Peer[] others = peers.Values.Where(x => x != peer && x.spawned && x.account != null).ToArray();
                foreach (Peer other in others)
                    SeedRemote(peer, other);
                Send(peer, Join(17, peer.account.guid, peer.companion));
                Send(peer, Join(15, peer.account.guid, peer.locomotion));
                if (!interactionRegistry.IsOptedIn(peer.account.guid))
                    DeliverWorld(world.SnapshotScene(peer.account.guid), null);
                if (isDay.HasValue) Send(peer, "30##" + (isDay.Value ? "True" : "False"));
                foreach (Peer other in peers.Values.Where(x => x != peer && x.announced)) RefreshRelationPair(peer, other);
                peer.announced = true;
                TryPublishStatus(true);
                Record("announced", peer.connection, 1, "snapshot_identity_bound");
            }
            catch
            {
                // A client sends its initial announcement once. Never leave a
                // partially delivered announcement advertised as complete.
                AbortAnnouncement(peer);
                throw;
            }
        }

        private void AbortAnnouncement(Peer peer)
        {
            peer.announced = false;
            reseeds.RemoveAll(x => x.actor == peer || x.viewer == peer);
            string relationPrefix = peer.account.guid + "|", relationSuffix = "|" + peer.account.guid;
            foreach (string key in relationSnapshots.Keys.Where(x => x.StartsWith(relationPrefix, StringComparison.Ordinal) ||
                x.EndsWith(relationSuffix, StringComparison.Ordinal)).ToArray()) relationSnapshots.Remove(key);
            foreach (Peer viewer in peers.Values.Where(x => x.spawned).ToArray())
            {
                try { RetireEntityFor(peer, viewer); }
                catch (Exception)
                {
                    // If cleanup itself cannot be queued, the affected viewer
                    // must reconnect rather than retain a half-created entity.
                    try { viewer.connection.Disconnect(); } catch (Exception) { }
                }
            }
            try { peer.connection.Disconnect(); } catch (Exception) { }
        }

        private void Own(Peer peer, string guid, string platform)
        {
            NebulaInstanceAccounts.Account account = accounts.Find(guid);
            if (account == null || account.platform != platform) throw new Rejected("unknown_session");
            if (account.allocated_instance_id != instanceId) throw new Rejected("session_not_allocated_to_instance");
            if (peer.account != null && (peer.account.guid != guid || peer.account.ps4_id != account.ps4_id))
                throw new Rejected("session_not_owned");
            foreach (Peer old in peers.Values.Where(x => x != peer && x.account != null && x.account.ps4_id == account.ps4_id).ToArray())
            {
                if (accounts.Find(old.account.guid) != null) throw new Rejected("account_already_connected");
                NetworkConnectionToClient connection = old.connection;
                Disconnected(connection);
                connection.Disconnect();
            }
            bool firstBinding = peer.account == null;
            peer.account = account;
            if (firstBinding)
            {
                if (SemanticBridgeRequired) interactionRegistry.Require(account.guid);
                if (wardrobeEntities.TryGetValue(account.ps4_id, out Peer retained))
                {
                    RememberPose(retained);
                    wardrobeEntities.Remove(account.ps4_id);
                    RetireEntity(retained);
                }
                peer.companion = account.selected_companion;
                peer.locomotion = account.selected_locomotion;
                peer.companionRevision = account.companion_revision;
                peer.locomotionRevision = account.locomotion_revision;
                RestorePose(peer);
                SeedRemotes(peer);
            }
        }

        private void BeginResourceSelection(Peer peer, string kind, string item)
        {
            try
            {
                Bound(peer);
                if (peer.resourcePending != null) throw new Rejected("resource_selection_pending");
                RequireResource(item, kind == "companions" ? peer.account.companion_ids : peer.account.locomotion_ids);
                long revision = kind == "companions" ? peer.companionRevision : peer.locomotionRevision;
                peer.resourcePending = resourceSelections.Begin(peer.account.guid, kind, item, revision, Now());
            }
            catch (Exception)
            {
                RestoreResourceSelection(peer, kind);
                throw;
            }
        }

        private void RestoreResourceSelection(Peer peer, string kind)
        {
            // Original 15/17 receivers only apply local visuals; they do not
            // invoke the wheel OnClick sender. Never manufacture a new request.
            try
            {
                Bound(peer);
                string item = kind == "companions" ? peer.account.selected_companion : peer.account.selected_locomotion;
                RequireResource(item, kind == "companions" ? peer.account.companion_ids : peer.account.locomotion_ids);
                Send(peer, Join(kind == "companions" ? 17 : 15, peer.account.guid, item));
            }
            catch (Exception) { } // disconnected/stale identity receives nothing
        }

        private void PumpResourceSelections()
        {
            foreach (Peer peer in peers.Values.ToArray())
            {
                var request = peer.resourcePending;
                if (request == null)
                {
                    if (peer.account == null) continue;
                    try
                    {
                        Bound(peer);
                        if (peer.account.companion_revision > peer.companionRevision)
                        {
                            peer.companion = peer.account.selected_companion;
                            peer.companionRevision = peer.account.companion_revision;
                            Broadcast(Join(17, peer.account.guid, peer.companion), peer);
                            Send(peer, Join(17, peer.account.guid, peer.companion));
                        }
                        if (peer.account.locomotion_revision > peer.locomotionRevision)
                        {
                            peer.locomotion = peer.account.selected_locomotion;
                            peer.locomotionRevision = peer.account.locomotion_revision;
                            Broadcast(Join(15, peer.account.guid, peer.locomotion), peer);
                            Send(peer, Join(15, peer.account.guid, peer.locomotion));
                        }
                    }
                    catch (Exception) { }
                    continue;
                }
                try
                {
                    Bound(peer); // re-acquire current GUID, account and exact allocation
                    if (peer.account.guid != request.guid || request.instance_id != instanceId || request.instance_owner != statusOwner)
                        throw new Rejected("resource_selection_session_changed");
                    if (Now() >= request.expires_at) throw new Rejected("resource_selection_deadline");
                    var ack = resourceSelections.Poll(request);
                    if (ack == null)
                    {
                        if (Now() >= request.expires_at) throw new Rejected("resource_selection_deadline");
                        continue;
                    }
                    if (ack.status != "committed") throw new Rejected("resource_selection_not_committed");
                    long exportedRevision = request.kind == "companions" ? peer.account.companion_revision : peer.account.locomotion_revision;
                    string exportedItem = request.kind == "companions" ? peer.account.selected_companion : peer.account.selected_locomotion;
                    if (exportedRevision < ack.revision) continue; // durable ack may precede atomic account export
                    if (exportedRevision != ack.revision || exportedItem != request.item_id)
                        throw new Rejected("resource_selection_ack_superseded");
                    RequireResource(request.item_id, request.kind == "companions" ? peer.account.companion_ids : peer.account.locomotion_ids);
                    if (request.kind == "companions")
                    {
                        peer.companion = request.item_id;
                        peer.companionRevision = ack.revision;
                    }
                    else
                    {
                        peer.locomotion = request.item_id;
                        peer.locomotionRevision = ack.revision;
                    }
                    Broadcast(Join(request.kind == "companions" ? 17 : 15, request.guid, request.item_id), peer);
                    Send(peer, Join(request.kind == "companions" ? 17 : 15, request.guid, request.item_id));
                    resourceSelections.Finish(request);
                    peer.resourcePending = null;
                }
                catch (Exception)
                {
                    Record("rejected", peer.connection, -1, "resource_selection_failed_or_stale");
                    if (peer.account != null && peer.account.guid == request.guid)
                        RestoreResourceSelection(peer, request.kind);
                    try { resourceSelections.Finish(request); } catch (Exception) { }
                    peer.resourcePending = null;
                }
            }
        }

        private void Bound(Peer peer)
        {
            if (peer.account == null) throw new Rejected("identity_not_bound");
            NebulaInstanceAccounts.Account current = accounts.Find(peer.account.guid);
            if (current == null || current.ps4_id != peer.account.ps4_id || current.platform != peer.account.platform ||
                current.allocated_instance_id != instanceId)
                throw new Rejected("session_not_current");
            peer.account = current;
        }

        private void Transform(Peer peer, string[] f)
        {
            Count(f, 2); Bound(peer);
            if (Unsigned(f[0]) != peer.netId) throw new Rejected("netid_not_owned");
            TransformData data = JsonUtility.FromJson<TransformData>(f[1]);
            if (data == null || !Finite(data.position) || !Finite(data.rotation) ||
                data.rotation.x * data.rotation.x + data.rotation.y * data.rotation.y +
                data.rotation.z * data.rotation.z + data.rotation.w * data.rotation.w < 0.000001f)
                throw new Rejected("invalid_transform");
            if (peer.inWardrobe) throw new Rejected("movement_while_in_wardrobe");
            peer.position = data.position;
            peer.rotation = data.rotation;
            ObservePose(peer);
            Broadcast(TransformReply(peer), peer);
        }

        private void Query(Peer peer, string[] f, string platform, int responseOpcode)
        {
            Count(f, 2); Own(peer, f[0], platform);
            Peer target = Entities().FirstOrDefault(x => x.announced && x.account.guid == f[1]);
            if (target == null) throw new Rejected("target_not_present");
            if (target == peer || !peer.visibleEntities.Contains(target.netId)) throw new Rejected("query_target_not_spawned_for_peer");
            if (responseOpcode == 2) Send(peer, TransformReply(target));
            else if (responseOpcode == 15) Send(peer, Join(15, target.account.guid, target.locomotion));
            else if (responseOpcode == 17) Send(peer, Join(17, target.account.guid, target.companion));
            else if (target.animationReply != null) Send(peer, target.animationReply);
            if (responseOpcode == 5)
            {
                // Native remote OnAvatarLoaded sends16,6,20,3, then removes
                // an old ghost before returning. The response is processed
                // after that callback, so this is a safe ghost transition.
                bool newlyLoaded = peer.loadedRemotes.Add(target.netId);
                if (newlyLoaded && target.connection != null && !target.inWardrobe)
                    DeliverWorld(world.SnapshotActor(peer.account.guid, target.account.guid), null);
                ShowWardrobe(target, peer);
            }
            // A player without a recorded animation has no invented animation.
        }

        private void Animation(Peer peer, string[] f, string platform)
        {
            if (f.Length < 6) throw new Rejected("invalid_animation_fields");
            Own(peer, f[0], platform);
            try { peer.animationReply = NebulaAnimationWire.BuildReply(f, peer.netId); }
            catch (NebulaAnimationWire.Rejected rejected) { throw new Rejected(rejected.Code); }
            Broadcast(peer.animationReply, peer);
        }

        private void Preference(Peer peer, string[] f, string platform)
        {
            Count(f, 3); Own(peer, f[0], platform);
            int key = Integer(f[1]);
            if (key != 0 && key != 1 && key != 2 && key != 3 && key != 4 && key != 15 && key != 21)
                throw new Rejected("unsupported_preference_replication");
            // HTTP service owns durable values. This command only replicates
            // the client's post-HTTP-save notification to current peers.
            Broadcast(Join(18, f), peer);
        }

        private void AnimationParameter(Peer peer, string[] f, string platform)
        {
            Count(f, 4); Own(peer, f[0], platform);
            int type = Integer(f[2]);
            if (type == 1) FloatValue(f[3]);
            else if (type == 3) Integer(f[3]);
            else if (type == 4) BooleanValue(f[3]);
            else if (type != 9) throw new Rejected("invalid_animator_parameter_type");
            Broadcast(Join(92, f), peer);
        }

        private void Occupancy(Peer peer, string[] f, string platform, bool acquire)
        {
            Count(f, 2); Own(peer, f[0], platform);
            int id = Integer(f[1]);
            if (id < 0) throw new Rejected("invalid_occupable_id");
            occupables.TryGetValue(id, out string occupant);
            if (acquire && (occupant == null || occupant == peer.account.guid))
            {
                occupables[id] = peer.account.guid;
                BroadcastLegacyInteraction(Join(9, f[0], f[1], peer.account.guid));
            }
            else if (occupant != null) Send(peer, Join(9, f[0], f[1], occupant));
            else Send(peer, Join(10, "", f[1])); // empty occupant in9 is ignored
        }

        private void InteractionRegistry(Peer peer, string[] f, string platform)
        {
            Count(f, 5); Own(peer, f[0], platform);
            if (!Int64.TryParse(f[1], NumberStyles.None, Invariant, out long seq))
                throw new Rejected("interaction_registry_seq_invalid");
            int part = Integer(f[2]), parts = Integer(f[3]);
            try
            {
                string json = interactionRegistry.AddChunk(peer.account.guid, seq, part, parts, f[4]);
                if (json == null) return;
                NebulaInteractionRegistry.WireDocument doc = JsonUtility.FromJson<NebulaInteractionRegistry.WireDocument>(json);
                if (doc == null || doc.seq != seq)
                    throw new NebulaInteractionRegistry.Rejected("registry_embedded_seq_mismatch");
                NebulaInteractionRegistry.Registration result = interactionRegistry.Register(
                    peer.account.guid, json, InteractionReadyGuids());
                if (result.Status == "accepted")
                {
                    interactionRebindDeadlines.Remove(peer.account.guid);
                    ClearInteractionPendingReason(peer);
                }
                string accepted = result.Status == "accepted" ? "1" : "0";
                Send(peer, Join(97, peer.account.guid, result.Seq.ToString(Invariant), accepted,
                    result.Status == "accepted" ? "accepted" : result.Reason));
                DeliverInteractions(result.Deliveries);
                if (result.Status == "accepted") Record("interaction_registry", peer.connection, 97, result.Status);
                else RecordInteractionPendingReason(peer, result, true);
            }
            catch (NebulaInteractionRegistry.Rejected error)
            {
                Send(peer, Join(97, peer.account.guid, seq.ToString(Invariant), "0", error.Code));
                Record("rejected", peer.connection, 97, error.Code);
            }
        }

        private IEnumerable<string> InteractionReadyGuids() => peers.Values
            .Where(x => x.account != null && interactionRegistry.IsReady(x.account.guid))
            .Select(x => x.account.guid).Distinct(StringComparer.Ordinal).ToArray();

        private static void ClearInteractionPendingReason(Peer peer)
        {
            if (peer == null) return;
            peer.interactionPendingSeq = Int64.MinValue;
            peer.interactionPendingReason = null;
            peer.interactionPendingReasonCount = 0;
        }

        private void RecordInteractionPendingReason(Peer peer, NebulaInteractionRegistry.Registration pending, bool initial)
        {
            if (peer == null || pending == null || pending.Status == "accepted" || String.IsNullOrEmpty(pending.Reason)) return;
            if (peer.interactionPendingSeq != pending.Seq)
            {
                peer.interactionPendingSeq = pending.Seq;
                peer.interactionPendingReason = null;
                peer.interactionPendingReasonCount = 0;
            }
            if (peer.interactionPendingReason == pending.Reason || peer.interactionPendingReasonCount >= 2) return;
            peer.interactionPendingReason = pending.Reason;
            peer.interactionPendingReasonCount++;
            Record(initial ? "interaction_registry" : "interaction_registry_pending", peer.connection, 97,
                initial ? pending.Status + ":" + pending.Reason : pending.Reason);
        }

        private void DeliverInteractions(IReadOnlyList<NebulaInteractionRegistry.Delivery> deliveries)
        {
            foreach (NebulaInteractionRegistry.Delivery delivery in deliveries)
            {
                Peer recipient = GuidPeer(delivery.TargetGuid, false);
                if (recipient != null && interactionRegistry.IsReady(delivery.TargetGuid))
                    Send(recipient, delivery.Payload);
            }
        }

        private void BroadcastLegacyInteraction(string plaintext)
        {
            foreach (Peer recipient in peers.Values.Where(x => x.spawned && x.account != null &&
                !interactionRegistry.IsOptedIn(x.account.guid))) Send(recipient, plaintext);
        }

        private void RefreshInteractionTrust()
        {
            if (interactionRegistry == null) return;
            string path = Path.Combine(stateDirectory, "instance-interactions.json");
            if (!File.Exists(path))
            {
                try { interactionRegistry.RefreshTrusted(null); }
                catch (NebulaInteractionRegistry.Rejected error) { Record("rejected", null, 97, error.Code); }
                return;
            }
            try
            {
                var info = new FileInfo(path);
                if (info.Length <= 0 || info.Length > 32 * 1024 * 1024)
                    throw new Rejected("interaction_registry_snapshot_size");
                string identity = info.Length.ToString(Invariant) + ":" + info.LastWriteTimeUtc.Ticks.ToString(Invariant);
                string text;
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var reader = new StreamReader(stream, new System.Text.UTF8Encoding(false, true))) text = reader.ReadToEnd();
                string[] invalidated = interactionRegistry.RefreshTrusted(text);
                interactionSnapshotIdentity = identity;
                var retained = new HashSet<string>(StringComparer.Ordinal);
                var expired = new HashSet<string>(StringComparer.Ordinal);
                foreach (string guid in peers.Values.Where(x => x.account != null &&
                    interactionRegistry.IsOptedIn(x.account.guid)).Select(x => x.account.guid).Distinct(StringComparer.Ordinal))
                {
                    try
                    {
                        NebulaInteractionRegistry.Registration pending = interactionRegistry.RetryPending(guid, InteractionReadyGuids());
                        if (pending != null && pending.Status == "accepted")
                        {
                            interactionRebindDeadlines.Remove(guid);
                            retained.Add(guid); DeliverInteractions(pending.Deliveries);
                            Peer owner = GuidPeer(guid, false);
                            if (owner != null) Send(owner, Join(97, guid, pending.Seq.ToString(Invariant), "1", "accepted"));
                            Record("interaction_registry_pending_committed", owner == null ? null : owner.connection, 97, "accepted");
                            ClearInteractionPendingReason(owner);
                        }
                        else if (pending != null) RecordInteractionPendingReason(GuidPeer(guid, false), pending, false);
                    }
                    catch (NebulaInteractionRegistry.Rejected error)
                    {
                        Record("rejected", null, 97, error.Code);
                        if (error.Code == "registry_pending_timeout") expired.Add(guid);
                    }
                }
                // A visitor with an old loaded layout cannot safely translate
                // the new epoch. Disconnecting forces the normal HTTP reload
                // and fresh instance registry instead of guessing migration.
                HousingBinding binding = ReadHousingBinding();
                foreach (string guid in invalidated.Where(x => !retained.Contains(x)))
                {
                    Peer stale = GuidPeer(guid, false);
                    if (stale != null && binding != null && stale.account.ps4_id == binding.owner_ps4_id)
                        interactionRebindDeadlines[guid] = Now() + 10.0;
                    else if (stale != null) stale.connection.Disconnect();
                }
                foreach (string guid in interactionRebindDeadlines.Where(x => Now() > x.Value).Select(x => x.Key).ToArray())
                {
                    interactionRebindDeadlines.Remove(guid);
                    Peer stale = GuidPeer(guid, false);
                    if (stale != null && !interactionRegistry.IsReady(guid)) stale.connection.Disconnect();
                }
                foreach (string guid in expired)
                {
                    Peer stale = GuidPeer(guid, false);
                    if (stale != null) stale.connection.Disconnect();
                }
            }
            catch (Exception error)
            {
                Record("interaction_registry_refresh_rejected", null, 97, error.GetType().Name);
            }
        }

        private void LeaveOccupancy(Peer peer, string[] f, string platform)
        {
            Count(f, 2); Own(peer, f[0], platform);
            int id = Integer(f[1]);
            if (!occupables.TryGetValue(id, out string occupant) || occupant != peer.account.guid)
                throw new Rejected("occupable_not_owned");
            occupables.Remove(id);
            BroadcastLegacyInteraction(Join(10, f));
        }

        private void Chat(Peer peer, string[] f, string platform)
        {
            Count(f, 5); Own(peer, f[0], platform);
            RequireChatAllowed(peer.account);
            RequireAnnounced(peer);
            int targetPlatform = Integer(f[2]), type = Integer(f[4]);
            if (targetPlatform < -1 || targetPlatform > 1) throw new Rejected("invalid_chat_platform");
            if (f[1].Length == 0 || f[3].Length == 0 || f[3].Length > 4096) throw new Rejected("invalid_chat");
            if (type == 0)
            {
                if (f[1] != "Public") throw new Rejected("unsupported_space_chat_group");
                foreach (Peer recipient in peers.Values.Where(x => x.announced && social.CanReceive(Actor(x), Actor(peer))))
                    Send(recipient, Join(13, f));
            }
            else if (type == 1)
            {
                NebulaInstanceAccounts.Account target = NamedAccount(f[1], targetPlatform, true);
                if (target.guid == peer.account.guid || !social.CanPrivateChat(Actor(peer), Actor(target))) throw new Rejected("private_chat_not_authorized");
                SendPrivate(peer, target, peer.account.guid, f[3]);
                Peer local = GuidPeer(target.guid, true);
                if (local != null) SendPrivate(local, peer.account, peer.account.guid, f[3]);
                else Relay(peer.account, target, "chat", 1, f[3]);
            }
            else throw new Rejected("unsupported_chat_type");
        }

        private void PrivateChat(Peer sender, Peer target, string authorGuid, string message)
        {
            // The native Chat consumer keys a tab by groupName. Each client
            // therefore receives its conversation partner as the group label.
            Send(sender, Join(13, authorGuid, target.account.username, target.account.PlatformNumber.ToString(Invariant), message, "1"));
            Send(target, Join(13, authorGuid, sender.account.username, sender.account.PlatformNumber.ToString(Invariant), message, "1"));
        }

        private void SendPrivate(Peer recipient, NebulaInstanceAccounts.Account partner, string authorGuid, string message)
        {
            Send(recipient, Join(13, authorGuid, partner.username, partner.PlatformNumber.ToString(Invariant), message, "1"));
        }

        private void StartTyping(Peer peer, string[] f, string platform)
        {
            Count(f, 2); Own(peer, f[0], platform);
            RequireChatAllowed(peer.account);
            RequireAnnounced(peer);
            StopTyping(peer);
            if (f[1] == "Public")
            {
                peer.typingPublic = true;
                foreach (Peer recipient in peers.Values.Where(x => x != peer && x.announced && social.CanReceive(Actor(x), Actor(peer))))
                    Send(recipient, Join(11, f));
            }
            else
            {
                // Typing11 has no target platform. Reject ambiguous names.
                NebulaInstanceAccounts.Account target = NamedAccount(f[1], -1, true);
                if (target.guid == peer.account.guid || !social.CanPrivateChat(Actor(peer), Actor(target))) throw new Rejected("private_typing_not_authorized");
                peer.typingTarget = target.guid;
                Peer local = GuidPeer(target.guid, true);
                if (local != null) Send(local, Join(11, peer.account.guid, peer.account.username));
                else Relay(peer.account, target, "typing", 0, "");
            }
        }

        private void StopTyping(Peer peer)
        {
            if (peer.account == null) return;
            if (peer.typingPublic)
                foreach (Peer recipient in peers.Values.Where(x => x != peer && x.announced)) Send(recipient, Join(12, peer.account.guid));
            if (peer.typingTarget != null)
            {
                Peer target = GuidPeer(peer.typingTarget, true);
                if (target != null) Send(target, Join(12, peer.account.guid));
                else
                {
                    NebulaInstanceAccounts.Account account = accounts.Find(peer.typingTarget);
                    if (account != null && IsOnline(account))
                        try { Relay(peer.account, account, "stop_typing", 0, ""); }
                        catch (Exception) { Record("rejected", peer.connection, 12, "social_stop_typing_not_delivered"); }
                }
            }
            peer.typingPublic = false; peer.typingTarget = null;
        }

        private static NebulaSocialState.Actor Actor(Peer peer) => new NebulaSocialState.Actor(peer.account.guid,
            peer.account.ps4_id, peer.account.username, peer.account.platform, peer.account.PlatformNumber);

        private static NebulaSocialState.Actor Actor(NebulaInstanceAccounts.Account account) => new NebulaSocialState.Actor(
            account.guid, account.ps4_id, account.username, account.platform, account.PlatformNumber);

        private NebulaInstanceAccounts.Account NamedAccount(string username, int platformNumber, bool online)
        {
            if (platformNumber < -1 || platformNumber > 1) throw new Rejected("invalid_target_platform");
            var matches = accounts.All().Where(x => x.username == username &&
                (platformNumber == -1 || x.PlatformNumber == platformNumber)).ToArray();
            if (matches.Length != 1) throw new Rejected(matches.Length == 0 ? "target_unknown" : "ambiguous_target_identity");
            if (online && !IsOnline(matches[0])) throw new Rejected("target_not_present");
            return matches[0];
        }

        private bool IsOnline(NebulaInstanceAccounts.Account account)
        {
            if (account == null || !System.Text.RegularExpressions.Regex.IsMatch(account.allocated_instance_id ?? "", "^[A-Za-z0-9_-]{1,128}$")) return false;
            if (account.allocated_instance_id == instanceId)
            {
                Peer local = GuidPeer(account.guid, true);
                return local != null && local.account.ps4_id == account.ps4_id && local.connection != null;
            }
            string directory = Path.Combine(stateDirectory, "instances", account.allocated_instance_id);
            if (!Directory.Exists(directory) || (File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0) return false;
            try
            {
                Status status = ReadShared<Status>(Path.Combine(directory, "instance-status.json"));
                AvatarSnapshot avatars = ReadShared<AvatarSnapshot>(Path.Combine(directory, "instance-avatar-state.json"));
                return status != null && status.format_version == 1 && status.instance_id == account.allocated_instance_id &&
                    status.listening && status.listener_bound && Fresh(status.heartbeat) && avatars != null && avatars.format_version == 1 &&
                    avatars.instance_id == status.instance_id && avatars.psidglobal == status.psidglobal && avatars.listening &&
                    Fresh(avatars.generation) && avatars.avatars != null && avatars.avatars.Count(x => x != null &&
                        x.guid == account.guid && x.ps4_id == account.ps4_id && x.connected && x.announced) == 1;
            }
            catch (Exception) { return false; }
        }

        private void Relay(NebulaInstanceAccounts.Account source, NebulaInstanceAccounts.Account target, string kind, int value, string text)
        {
            if (!IsOnline(target)) throw new Rejected("social_relay_target_not_present");
            double now = Now();
            socialMailbox.Enqueue(new NebulaSocialMailbox.Envelope {event_id = Guid.NewGuid().ToString("N"), kind = kind,
                source_guid = source.guid, target_guid = target.guid, source_account = source.ps4_id, target_account = target.ps4_id,
                source_instance = instanceId, target_instance = target.allocated_instance_id, value = value, text = text,
                created_at = now, expires_at = now + 15}, now);
        }

        private void DeliverSocialRelay(NebulaSocialMailbox.Envelope entry)
        {
            NebulaInstanceAccounts.Account source = accounts.Find(entry.source_guid);
            NebulaInstanceAccounts.Account target = accounts.Find(entry.target_guid);
            Peer recipient = GuidPeer(entry.target_guid, true);
            if (source == null || target == null || source.ps4_id != entry.source_account || target.ps4_id != entry.target_account ||
                target.allocated_instance_id != instanceId || recipient == null ||
                (entry.kind != "stop_typing" && (source.allocated_instance_id != entry.source_instance || !IsOnline(source))))
                throw new Rejected("social_relay_session_not_current_or_present");
            Bound(recipient);
            // Recheck current authority at delivery, including messages queued
            // in another scene immediately before the mute was committed.
            if (entry.kind == "chat" || entry.kind == "typing") RequireChatAllowed(source);
            if (entry.kind != "refresh" && entry.kind != "stop_typing" && !social.CanReceive(Actor(target), Actor(source)))
                throw new Rejected("social_relay_relation_denied");
            if (entry.kind == "request") SendNotification(recipient, source, entry.value, "");
            else if (entry.kind == "chat")
            {
                if (!social.CanPrivateChat(Actor(source), Actor(target))) throw new Rejected("private_chat_not_authorized");
                SendPrivate(recipient, source, source.guid, entry.text);
            }
            else if (entry.kind == "typing")
            {
                if (!social.CanPrivateChat(Actor(source), Actor(target))) throw new Rejected("private_typing_not_authorized");
                Send(recipient, Join(11, source.guid, source.username));
            }
            else if (entry.kind == "stop_typing") Send(recipient, Join(12, source.guid));
            else if (entry.kind == "accepted")
            {
                if (entry.value == 1)
                {
                    social.ObserveFriendship(Actor(source), Actor(target));
                    SendNotification(recipient, source, 5, "");
                    SendRelationExternal(recipient, source);
                }
                else
                {
                    if (!social.CanPrivateChat(Actor(source), Actor(target))) throw new Rejected("private_chat_not_authorized");
                    SendPrivate(recipient, source, target.guid, "Private chat connected.");
                }
            }
            else if (entry.kind == "refresh")
            {
                if (entry.value == 21) social.ObserveFriendship(Actor(source), Actor(target), false);
                else ObserveRelationRefresh(Actor(source), Actor(target), entry.value);
                Send(recipient, Join(entry.value, source.username, source.PlatformNumber.ToString(Invariant)));
                SendRelationExternal(recipient, source);
            }
        }

        private Peer NamedPeer(string username, int platformNumber)
        {
            if (platformNumber < -1 || platformNumber > 1) throw new Rejected("invalid_target_platform");
            Peer[] matches = peers.Values.Where(x => x.announced && x.account != null &&
                x.account.username == username && (platformNumber == -1 || x.account.PlatformNumber == platformNumber)).ToArray();
            if (matches.Length != 1) throw new Rejected(matches.Length == 0 ? "target_not_present" : "ambiguous_target_identity");
            Bound(matches[0]);
            return matches[0];
        }

        private Peer GuidPeer(string guid, bool announced) => peers.Values.FirstOrDefault(x =>
            x.spawned && (!announced || x.announced) && x.account != null && x.account.guid == guid);

        private void Notification(Peer peer, string[] f)
        {
            Count(f, 4); Bound(peer);
            RequireAnnounced(peer);
            if (f[0] != peer.account.username) throw new Rejected("notification_sender_mismatch");
            int type = Integer(f[2]);
            NebulaInstanceAccounts.Account target = NamedAccount(f[1], Integer(f[3]), true);
            social.Request(Actor(peer), Actor(target), type);
            // C2S19 has four fields. S2C19 has five entirely different fields.
            try
            {
                Peer local = GuidPeer(target.guid, true);
                if (local != null) SendNotification(local, peer, type, "");
                else Relay(peer.account, target, "request", type, "");
            }
            catch { social.CancelRequest(Actor(peer), Actor(target), type); throw; }
        }

        private void SendNotification(Peer recipient, Peer source, int type, string arguments)
        { SendNotification(recipient, source.account, type, arguments); }

        private void SendNotification(Peer recipient, NebulaInstanceAccounts.Account source, int type, string arguments)
        {
            Send(recipient, Join(19, source.username, source.PlatformNumber.ToString(Invariant),
                type.ToString(Invariant), arguments, DateTime.UtcNow.Ticks.ToString(Invariant)));
            if (type == 5)
                informationalNotifications.Record(recipient.account.guid, source.username, source.PlatformNumber, Now());
        }

        private void AcceptNotification(Peer peer, string[] f, string platform)
        {
            if (f.Length != 4 && f.Length != 3) throw new Rejected("wrong_field_count");
            Own(peer, f[0], platform);
            RequireAnnounced(peer);
            int type = Integer(f[2]);
            if (f.Length == 3)
            {
                if (type != 11) throw new Rejected("invalid_platform_omitting_acceptance");
                throw new Rejected("space_game_notification_not_reconstructed");
            }
            if (type == 3 || type == 4)
            {
                var ack = notificationInbox.Accept(peer.account.ps4_id, peer.account.guid, f[1], type, Integer(f[3]), Now());
                notificationInbox.MarkAccepted(PersistNotificationAcknowledgement(ack));
                return; // Bookkeeping only: ownership was durably granted by HTTP.
            }
            if (type == 5)
            {
                informationalNotifications.Accept(peer.account.guid, f[1], Integer(f[3]), type, Now());
                return; // Acknowledge a prior friend-accepted notice; no new relation grant.
            }
            NebulaInstanceAccounts.Account requester = NamedAccount(f[1], Integer(f[3]), true);
            social.Accept(Actor(peer), Actor(requester), type);
            Peer localRequester = GuidPeer(requester.guid, true);
            if (type == 1)
            {
                if (localRequester != null)
                {
                    SendNotification(localRequester, peer, 5, "");
                    RefreshRelationPair(peer, localRequester);
                }
                else
                {
                    Relay(peer.account, requester, "accepted", 1, "");
                    SendRelationExternal(peer, requester);
                }
            }
            else
            {
                // Authored local policy: a first message opens the two native
                // private tabs. The original server's wording is not shipped.
                if (localRequester != null) PrivateChat(localRequester, peer, requester.guid, "Private chat connected.");
                else
                {
                    Relay(peer.account, requester, "accepted", 0, "");
                    SendPrivate(peer, requester, requester.guid, "Private chat connected.");
                }
            }
        }

        private void DeclineNotification(Peer peer, string[] f, string platform)
        {
            Count(f, 4); Own(peer, f[0], platform);
            RequireAnnounced(peer);
            Peer requester = NamedPeer(f[1], Integer(f[2]));
            social.Decline(Actor(peer), Actor(requester), Integer(f[3]));
        }

        private void SocialRefresh(Peer peer, int opcode, string[] f, string platform)
        {
            if (f.Length != 3 && !(opcode == 21 && f.Length == 2)) throw new Rejected("wrong_field_count");
            Own(peer, f[0], platform);
            RequireAnnounced(peer);
            NebulaInstanceAccounts.Account target = NamedAccount(f[1], f.Length == 3 ? Integer(f[2]) : -1, false);
            if (target.guid == peer.account.guid) throw new Rejected("social_target_is_self");
            if (opcode == 21) social.RemoveFriendship(Actor(peer), Actor(target));
            else ObserveRelationRefresh(Actor(peer), Actor(target), opcode);
            //22..25 are notifications after a durable HTTP operation. Read
            // the snapshot plus the bounded authenticated publication overlay;
            // HTTP remains the persistence authority.
            Send(peer, Join(opcode, target.username, target.PlatformNumber.ToString(Invariant)));
            Peer local = GuidPeer(target.guid, true);
            if (local != null) SendRelationSnapshot(peer, local);
            else SendRelationExternal(peer, target);
            if (local != null)
            {
                Send(local, Join(opcode, peer.account.username, peer.account.PlatformNumber.ToString(Invariant)));
                SendRelationSnapshot(local, peer);
            }
            else if (IsOnline(target)) Relay(peer.account, target, "refresh", opcode, "");
        }

        private void ObserveRelationRefresh(NebulaSocialState.Actor owner, NebulaSocialState.Actor target, int opcode)
        {
            switch (opcode)
            {
                case 22: social.ObserveRelation(owner, target, "silenced", false); return;
                case 23: social.ObserveRelation(owner, target, "silenced", true); return;
                case 24: social.ObserveRelation(owner, target, "block", true); return;
                case 25: social.ObserveRelation(owner, target, "block", false); return;
                default: throw new Rejected("invalid_relation_refresh_opcode");
            }
        }

        private static string RelationSnapshotKey(string viewerGuid, string targetGuid) => viewerGuid + "|" + targetGuid;

        private void SendRelationSnapshot(Peer viewer, Peer target)
        {
            string key = RelationSnapshotKey(viewer.account.guid, target.account.guid);
            NebulaSocialRelationSnapshot.State next = social.RelationSnapshot(Actor(viewer), Actor(target));
            NebulaSocialRelationSnapshot.Plan plan;
            if (relationSnapshots.TryGetValue(key, out NebulaSocialRelationSnapshot.State previous))
                plan = NebulaSocialRelationSnapshot.Transition(previous, next);
            else plan = new NebulaSocialRelationSnapshot.Plan(false, NebulaSocialRelationSnapshot.Codes(next));
            relationSnapshots[key] = next;
            if (plan.ReseedEntity && RetireEntityFor(target, viewer))
            {
                QueueReseed(target, viewer, Time.frameCount + 2, plan.Codes);
                return;
            }
            foreach (int code in plan.Codes)
                Send(viewer, Join(28, target.account.guid, code.ToString(Invariant)));
        }

        private void SendRelationExternal(Peer viewer, NebulaInstanceAccounts.Account target)
        {
            NebulaSocialRelationSnapshot.State next = social.RelationSnapshot(Actor(viewer), Actor(target));
            relationSnapshots[RelationSnapshotKey(viewer.account.guid, target.guid)] = next;
            foreach (int code in NebulaSocialRelationSnapshot.Codes(next))
                Send(viewer, Join(28, target.guid, code.ToString(Invariant)));
        }

        private void RefreshRelationPair(Peer a, Peer b)
        {
            SendRelationSnapshot(a, b);
            SendRelationSnapshot(b, a);
        }

        private NebulaMinigameState.Identity ResolveMinigameIdentity(string guid)
        {
            Peer peer = GuidPeer(guid, false);
            if (peer == null) return null;
            Bound(peer);
            return new NebulaMinigameState.Identity(peer.account.guid, peer.account.username, peer.account.ps4_id);
        }

        private NebulaWorldState.Identity ResolveWorldIdentity(string guid)
        {
            Peer peer = GuidPeer(guid, false);
            if (peer == null) return null;
            Bound(peer);
            return new NebulaWorldState.Identity(peer.account.guid, peer.account.username, peer.account.ps4_id);
        }

        private void DeliverWorld(IReadOnlyList<NebulaWorldState.Delivery> deliveries, Peer source)
        {
            foreach (NebulaWorldState.Delivery delivery in deliveries)
            {
                bool legacyGeneric = delivery.Payload != null && delivery.Payload.StartsWith("94#", StringComparison.Ordinal);
                if (delivery.TargetGuid != null)
                {
                    Peer recipient = GuidPeer(delivery.TargetGuid, false);
                    if (recipient != null && recipient.account.guid != delivery.ExceptGuid &&
                        !(legacyGeneric && interactionRegistry.IsOptedIn(recipient.account.guid))) Send(recipient, delivery.Payload);
                }
                else
                    foreach (Peer recipient in peers.Values.Where(x => x.announced && x.account.guid != delivery.ExceptGuid &&
                        (source == null || source == x || x.loadedRemotes.Contains(source.netId)) &&
                        !(legacyGeneric && interactionRegistry.IsOptedIn(x.account.guid)))) Send(recipient, delivery.Payload);
            }
        }

        private void DeliverMinigame(IReadOnlyList<NebulaMinigameState.Delivery> deliveries)
        {
            foreach (NebulaMinigameState.Delivery delivery in deliveries)
            {
                if (delivery.TargetGuid != null)
                {
                    Peer recipient = GuidPeer(delivery.TargetGuid, false);
                    if (recipient != null && recipient.account.guid != delivery.ExceptGuid) Send(recipient, delivery.Payload);
                }
                else
                    foreach (Peer recipient in peers.Values.Where(x => x.announced && x.account.guid != delivery.ExceptGuid))
                        Send(recipient, delivery.Payload);
            }
        }

        private void Command(NetworkConnectionToClient connection, CommandMessage message)
        {
            try
            {
                if (!peers.TryGetValue(connection.connectionId, out Peer peer) || peer.connection != connection ||
                    !peer.spawned || !connection.isReady || !connection.isAuthenticated)
                    throw new Rejected("mirror_command_before_ready_player");
                Bound(peer);
                if (message.netId != peer.netId) throw new Rejected("mirror_command_netid_not_owned");
                if (peer.inWardrobe) throw new Rejected("mirror_command_while_in_wardrobe");
                if (NebulaMirrorCommands.IsSpeed(message))
                {
                    if (!NebulaMirrorCommands.TryReadSpeed(message, out float speed)) throw new Rejected("invalid_speed_command");
                    // The shipped native UserCode is a ret stub. Assignment
                    // and replication here are deliberate replacement policy.
                    peer.speed = speed;
                    if (peer.announced)
                        foreach (Peer recipient in peers.Values.Where(x => x != peer && x.spawned && x.visibleEntities.Contains(peer.netId)))
                            recipient.connection.Send(new EntityStateMessage {netId = peer.netId,
                                payload = new ArraySegment<byte>(NebulaSpawnState.SpeedDelta(speed))});
                    return;
                }
                if (NebulaMirrorCommands.IsTransform(message))
                {
                    if (!NebulaMirrorCommands.TryReadTransform(message, out NebulaMirrorCommands.TransformCommand command))
                        throw new Rejected("invalid_mirror_transform_command");
                    if (command.position.HasValue) peer.position = command.position.Value;
                    if (command.rotation.HasValue) peer.rotation = command.rotation.Value;
                    if (command.scale.HasValue) peer.scale = command.scale.Value;
                    if (command.position.HasValue || peer.positionUpdatedAt > 0) ObservePose(peer);
                    if (peer.announced)
                        foreach (Peer recipient in peers.Values.Where(x => x.spawned && x.visibleEntities.Contains(peer.netId)))
                            recipient.connection.Send(new RpcMessage {netId = peer.netId, componentIndex = 0,
                                functionHash = command.rpcHash, payload = command.payload}, command.channel);
                    return;
                }
                Record("unsupported_mirror_command", connection, -1,
                    "component=" + message.componentIndex.ToString(Invariant) + ";hash=" + message.functionHash.ToString(Invariant));
            }
            catch (Rejected error) { Record("rejected", connection, -1, error.Message); }
            catch (Exception) { Record("rejected", connection, -1, "invalid_mirror_command_or_snapshot"); }
        }

        private void Disconnected(NetworkConnectionToClient connection)
        {
            if (!peers.TryGetValue(connection.connectionId, out Peer peer) || peer.connection != connection) return;
            try { StopTyping(peer); }
            catch (Exception) { peer.typingPublic = false; peer.typingTarget = null; }
            ClearInteractionPendingReason(peer);
            reseeds.RemoveAll(x => x.actor == peer || x.viewer == peer);
            peers.Remove(connection.connectionId);
            if (peer.account != null)
            {
                interactionRebindDeadlines.Remove(peer.account.guid);
                string relationPrefix = peer.account.guid + "|", relationSuffix = "|" + peer.account.guid;
                foreach (string key in relationSnapshots.Keys.Where(x => x.StartsWith(relationPrefix, StringComparison.Ordinal) ||
                    x.EndsWith(relationSuffix, StringComparison.Ordinal)).ToArray()) relationSnapshots.Remove(key);
                try { DeliverInteractions(interactionRegistry.Disconnect(peer.account.guid, InteractionReadyGuids())); }
                catch (NebulaInteractionRegistry.Rejected error) { Record("rejected", connection, -1, error.Code); }
                RememberPose(peer);
                social.Disconnect(peer.account.guid, AccountForCleanup(peer.account.guid) == null);
                notificationInbox.Disconnect(peer.account.guid);
                informationalNotifications.Disconnect(peer.account.guid);
                try { DeliverWorld(world.Disconnect(peer.account.guid), peer); }
                catch (NebulaWorldState.Rejected error) { Record("rejected", connection, -1, error.Code); }
                try { DeliverMinigame(minigames.Disconnect(peer.account.guid)); }
                catch (NebulaMinigameState.Rejected error) { Record("rejected", connection, -1, error.Code); }
                foreach (int id in occupables.Where(x => x.Value == peer.account.guid).Select(x => x.Key).ToArray())
                {
                    occupables.Remove(id);
                    BroadcastLegacyInteraction(Join(10, peer.account.guid, id.ToString(Invariant)));
                }
                NebulaInstanceAccounts.Account current = AccountForCleanup(peer.account.guid);
                if (peer.announced && peer.inWardrobe && current != null && current.ps4_id == peer.account.ps4_id &&
                    current.platform == peer.account.platform && current.allocated_instance_id == instanceId && WardrobeLease(current))
                {
                    peer.account = current;
                    peer.connection = null;
                    wardrobeEntities[peer.account.ps4_id] = peer;
                }
                else if (peer.spawned) RetireEntity(peer);
            }
            Record("disconnected", connection, -1, "local_presence_removed");
            TryPublishStatus(true);
        }

        private void Broadcast(string plaintext, Peer except)
        {
            foreach (Peer recipient in peers.Values.Where(x => x.spawned && x != except &&
                (except == null || x.visibleEntities.Contains(except.netId)))) Send(recipient, plaintext);
        }

        private static void Send(Peer peer, string plaintext)
        {
            peer.connection.Send(new NebulaMessage {data = NebulaApplicationCrypto.EncryptReply(plaintext)});
        }

        private NebulaInstanceAccounts.Account AccountForCleanup(string guid)
        {
            // Cleanup may remove authority, never confer or retain it.
            try { return accounts.Find(guid); } catch (Exception) { return null; }
        }

        private static void RequireChatAllowed(NebulaInstanceAccounts.Account account)
        {
            if (account == null || account.ChatMuted(Now())) throw new Rejected("chat_restricted");
        }

        private static string JoinedReply(Peer peer) => Join(1, peer.netId.ToString(Invariant), peer.account.guid,
            peer.account.username, peer.account.PlatformNumber.ToString(Invariant));

        private static string TransformReply(Peer peer) => Join(2, peer.netId.ToString(Invariant),
            JsonUtility.ToJson(new TransformData {position = peer.position, rotation = peer.rotation}));

        private static string Join(int opcode, params string[] fields) => opcode.ToString(Invariant) +
            (fields.Length == 0 ? "" : "#" + String.Join("#", fields));

        private static void RequireAnnounced(Peer peer)
        {
            if (!peer.announced) throw new Rejected("social_before_player_announcement");
        }

        private static void RequireResource(string selected, string[] owned)
        {
            if (selected.Length != 0 && (owned == null || !owned.Contains(selected, StringComparer.Ordinal)))
                throw new Rejected("resource_selection_not_owned");
        }

        private static void Count(string[] fields, int count)
        {
            if (fields.Length != count) throw new Rejected("wrong_field_count");
        }

        private static int Integer(string value)
        {
            if (!Int32.TryParse(value, NumberStyles.Integer, Invariant, out int result)) throw new Rejected("invalid_int32");
            return result;
        }

        private static uint Unsigned(string value)
        {
            if (!UInt32.TryParse(value, NumberStyles.None, Invariant, out uint result)) throw new Rejected("invalid_uint32");
            return result;
        }

        private static float FloatValue(string value)
        {
            if (!Single.TryParse(value, NumberStyles.Float, Invariant, out float result) || !Finite(result)) throw new Rejected("invalid_float32");
            return result;
        }

        private static bool BooleanValue(string value)
        {
            if (!Boolean.TryParse(value, out bool result)) throw new Rejected("invalid_boolean");
            return result;
        }

        private static bool Finite(float value) => !Single.IsNaN(value) && !Single.IsInfinity(value);
        private static bool Finite(Vector3 value) => Finite(value.x) && Finite(value.y) && Finite(value.z);
        private static bool Finite(Quaternion value) => Finite(value.x) && Finite(value.y) && Finite(value.z) && Finite(value.w);

        private void Record(string kind, NetworkConnectionToClient connection, int opcode, string detail)
        {
            journal?.WriteLine(JsonUtility.ToJson(new JournalEntry {
                utc = DateTime.UtcNow.ToString("O", Invariant), kind = kind,
                connection = connection == null ? 0 : connection.connectionId,
                opcode = opcode, detail = detail
            }));
        }

        private void PublishStatus(bool listening)
        {
            if (stateDirectory == null) return;
            bool bound = instanceTransport != null && instanceTransport.ServerListening;
            listening = listening && bound && NetworkServer.active && Transport.activeTransport == instanceTransport;
            if (!listening && !publishedStatus) return;
            HousingBinding housing = ReadHousingBinding();
            bool semanticTrusted = interactionRegistry != null && interactionRegistry.HasTrustedProfile;
            bool sceneVerified = world.HasVerifiedInventory || (SemanticBridgeRequired && semanticTrusted);
            bool coreEligible = NebulaCoreReadiness.Eligible(coreTestProfile, spaceId, listening,
                minigames.BoardTableCount, minigames.DartsTableCount, sceneVerified, housing != null, semanticTrusted);
            var value = new Status {
                state = coreEligible ? "listening_core_test_candidate" : listening ? "listening_incomplete" : "stopped_incomplete", port = port,
                bind = bindAddress.ToString(), ip = advertisedAddress,
                instance_id = instanceId, psidglobal = spaceId,
                players = peers.Count, heartbeat = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
                listening = listening, owner = statusOwner,
                listener_bound = listening && bound, readiness_scope = coreTestProfile ?? "closed", core_test_eligible = coreEligible,
                scene_registry_verified = sceneVerified, interaction_bridge_required = SemanticBridgeRequired,
                interaction_registry_trusted = semanticTrusted, housing_bound = housing != null,
                housing_owner = housing == null ? "" : housing.owner_ps4_id,
                board_tables = minigames.BoardTableCount, darts_tables = minigames.DartsTableCount,
                implemented_opcodes = new[] {"1", "2", "3", "4", "6", "8", "9", "10", "11", "12", "13:space_private_local_policy",
                    "15", "16", "17", "18", "19:chat_friend_invite", "20", "21", "22", "23", "24", "25", "26:chat_friend",
                    "29:wardrobe_lease", "30", "31:verified_scene_boats", "32:ttt_lobby", "33:ttt_lobby", "34:ttt", "35:ttt", "36", "37",
                    "44:receipt_coffee", "46:receipt_oktoberfest", "80:lobby", "81:lobby", "82:lobby", "86:lobby", "92", "94:verified_scene_interactables",
                    "97:semantic_interaction_registry_v1"}
            };
            string path = Path.Combine(instanceDirectory, "instance-status.json");
            string temporary = Path.Combine(instanceDirectory, "instance-status." + statusOwner + ".tmp");
            try
            {
                File.WriteAllText(temporary, JsonUtility.ToJson(value, true), new System.Text.UTF8Encoding(false));
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
                publishedStatus = true;
                PublishPresence(listening);
                PublishAvatars(listening);
                PublishPoses();
            }
            finally
            {
                if (File.Exists(temporary)) File.Delete(temporary);
            }
        }

        private HousingBinding ReadHousingBinding()
        {
            if (!NebulaCoreReadiness.IsPersonalSpace(spaceId)) return null;
            try
            {
                HousingBindings snapshot = ReadShared<HousingBindings>(Path.Combine(stateDirectory, "instance-housing.json"));
                if (snapshot == null || snapshot.format_version != 1 || !Fresh(snapshot.generation) || snapshot.bindings == null)
                    return null;
                HousingBinding[] matches = snapshot.bindings.Where(x => x != null && x.instance_id == instanceId).ToArray();
                if (matches.Length != 1) return null;
                HousingBinding row = matches[0];
                if (row.psidglobal != spaceId || !NebulaCoreReadiness.IsPersonalSpace(row.logical_space_key) ||
                    String.IsNullOrEmpty(row.owner_ps4_id) || !accounts.All().Any(x => x.ps4_id == row.owner_ps4_id)) return null;
                return row;
            }
            catch (Exception) { return null; }
        }

        private static bool Fresh(double timestamp)
        {
            double age = Now() - timestamp;
            return !Double.IsNaN(age) && !Double.IsInfinity(age) && age >= 0 && age <= 15;
        }

        private static T ReadShared<T>(string path) where T : class
        {
            if (!File.Exists(path) || new FileInfo(path).Length > 16 * 1024 * 1024) return null;
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(stream, new System.Text.UTF8Encoding(false, true)))
                return JsonUtility.FromJson<T>(reader.ReadToEnd());
        }

        private void PublishPresence(bool listening)
        {
            var present = new List<NebulaInstancePresence.Player>();
            if (listening)
                foreach (Peer peer in Entities())
                {
                    NebulaInstanceAccounts.Account current = accounts.Find(peer.account.guid);
                    if (current != null && current.ps4_id == peer.account.ps4_id && current.platform == peer.account.platform &&
                        current.allocated_instance_id == instanceId)
                        present.Add(new NebulaInstancePresence.Player {guid = current.guid, status = peer.inWardrobe ? 3 : 0});
                }
            var snapshot = new NebulaInstancePresence(instanceId, spaceId, Now(), present);
            string path = Path.Combine(instanceDirectory, "instance-presence.json");
            string temporary = Path.Combine(instanceDirectory, "instance-presence." + statusOwner + ".tmp");
            try
            {
                File.WriteAllText(temporary, JsonUtility.ToJson(snapshot, true), new System.Text.UTF8Encoding(false));
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        private void PublishAvatars(bool listening)
        {
            var value = new AvatarSnapshot {instance_id = instanceId, psidglobal = spaceId, generation = Now(), listening = listening,
                avatars = listening ? Entities().Select(x => new AvatarRecord {guid = x.account.guid, ps4_id = x.account.ps4_id,
                    net_id = x.netId, connected = x.connection != null, announced = x.announced, in_wardrobe = x.inWardrobe,
                    position = x.position, rotation = x.rotation, scale = x.scale, position_updated_at = x.positionUpdatedAt}).ToArray()
                    : Array.Empty<AvatarRecord>()};
            WriteAtomic("instance-avatar-state.json", JsonUtility.ToJson(value, true));
        }

        private void PublishPoses()
        {
            foreach (Peer entity in Entities()) RememberPose(entity);
            WriteAtomic("instance-poses.json", JsonUtility.ToJson(new PoseSnapshot {instance_id = instanceId,
                psidglobal = spaceId, generation = Now(), poses = poses.Values.OrderBy(x => x.ps4_id, StringComparer.Ordinal).ToArray()}, true));
        }

        private int? ClaimConsumable(string guid, string accountId, string kind, string receipt)
        {
            if ((kind != "coffee" && kind != "oktoberfest") || receipt == null || receipt.Length != 32 ||
                receipt.Any(c => !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))) return null;
            string pending = Path.Combine(stateDirectory, "consumable-receipts", receipt + ".json");
            string claimedDirectory = Path.Combine(stateDirectory, "consumable-claims");
            string claimed = Path.Combine(claimedDirectory, receipt + ".json");
            try
            {
                var info = new FileInfo(pending);
                if (!info.Exists || info.Length <= 0 || info.Length > 16384 || File.Exists(claimed)) return null;
                ConsumableReceipt value;
                string content;
                using (var stream = new FileStream(pending, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var reader = new StreamReader(stream, new System.Text.UTF8Encoding(false, true)))
                    content = reader.ReadToEnd();
                if (!ExactReceiptFields(content)) return null;
                value = JsonUtility.FromJson<ConsumableReceipt>(content);
                double now = Now();
                if (value == null || value.format_version != 1 || value.receipt_id != receipt || value.guid != guid ||
                    value.policy != "local_consumable_receipt_v1" || value.ps4_id != accountId || value.kind != kind ||
                    value.table_id != 0 || value.reward_index < 0 || value.use_count <= 0 ||
                    Double.IsNaN(value.issued_at) || Double.IsInfinity(value.issued_at) ||
                    Double.IsNaN(value.expires_at) || Double.IsInfinity(value.expires_at) ||
                    value.issued_at <= 0 || value.issued_at > now || value.expires_at <= now || value.expires_at <= value.issued_at) return null;
                Directory.CreateDirectory(claimedDirectory);
                // No overwrite: exactly one instance can claim this immutable
                // receipt across the shared state root on the same volume.
                File.Move(pending, claimed);
                return value.use_count;
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException || error is ArgumentException)
            {
                Record("consumable_claim_rejected", null, -1, "invalid_expired_or_already_claimed_receipt");
                return null;
            }
        }

        private static bool ExactReceiptFields(string json)
        {
            var strings = new HashSet<string>(new[] {"policy", "receipt_id", "guid", "ps4_id", "kind"}, StringComparer.Ordinal);
            var integers = new HashSet<string>(new[] {"format_version", "table_id", "use_count", "reward_index"}, StringComparer.Ordinal);
            var expected = new HashSet<string>(strings.Concat(integers).Concat(new[] {"issued_at", "expires_at"}), StringComparer.Ordinal);
            int at = 0;
            Action whitespace = () => { while (at < json.Length && Char.IsWhiteSpace(json[at])) ++at; };
            whitespace();
            if (at >= json.Length || json[at++] != '{') return false;
            while (true)
            {
                whitespace();
                if (at >= json.Length) return false;
                if (json[at] == '}') { ++at; whitespace(); return expected.Count == 0 && at == json.Length; }
                if (json[at++] != '"') return false;
                int start = at;
                while (at < json.Length && json[at] != '"')
                    if (json[at++] == '\\') return false; // issuer uses literal canonical keys
                if (at >= json.Length) return false;
                string key = json.Substring(start, at++ - start);
                if (!expected.Remove(key)) return false;
                whitespace(); if (at >= json.Length || json[at++] != ':') return false;
                whitespace(); if (at >= json.Length) return false;
                if (strings.Contains(key))
                {
                    if (json[at++] != '"') return false;
                    bool closed = false;
                    while (at < json.Length)
                    {
                        char c = json[at++];
                        if (c == '"') { closed = true; break; }
                        if (c < 32) return false;
                        if (c == '\\' && ++at > json.Length) return false;
                    }
                    if (!closed) return false;
                }
                else
                {
                    start = at;
                    while (at < json.Length && json[at] != ',' && json[at] != '}') ++at;
                    string token = json.Substring(start, at - start).Trim();
                    if (integers.Contains(key))
                    { if (!Int32.TryParse(token, NumberStyles.None, Invariant, out int ignored)) return false; }
                    else if (!Double.TryParse(token, NumberStyles.Float, Invariant, out double number) ||
                        Double.IsNaN(number) || Double.IsInfinity(number)) return false;
                }
                whitespace();
                if (at >= json.Length) return false;
                if (json[at] == '}') continue;
                if (json[at++] != ',') return false;
                whitespace(); if (at >= json.Length || json[at] == '}') return false;
            }
        }

        private void WriteAtomic(string filename, string contents)
        {
            string path = Path.Combine(instanceDirectory, filename), temporary = path + "." + statusOwner + ".tmp";
            try
            {
                File.WriteAllText(temporary, contents, new System.Text.UTF8Encoding(false));
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        private void TryPublishStatus(bool listening)
        {
            try { PublishStatus(listening); }
            catch (IOException) { Record("descriptor_error", null, -1, "atomic_publication_failed"); }
            catch (UnauthorizedAccessException) { Record("descriptor_error", null, -1, "descriptor_access_failed"); }
        }

        private void Stop()
        {
            if (started)
            {
                started = false;
                NetworkServer.Shutdown();
                TryPublishStatus(false);
            }
            journal?.Dispose();
            journal = null;
            instanceLock?.Dispose();
            instanceLock = null;
        }

        private void OnApplicationQuit() => Stop();
        private void OnDestroy() => Stop();
    }
}
