using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace NebulaPreservation
{
    // Pure replacement state policy. Native contracts, source hashes and limits:
    // protocol/tcp-world-interactions.json. No Unity, Mirror, I/O or clocks.
    public sealed class NebulaWorldState
    {
        public sealed class Identity
        {
            public readonly string Guid, DisplayName, PlatformId;
            public Identity(string guid, string displayName, string platformId)
            { Guid = guid; DisplayName = displayName; PlatformId = platformId; }
        }

        public sealed class Delivery
        {
            public readonly string TargetGuid, ExceptGuid, Payload;
            private Delivery(string target, string except, string payload)
            { TargetGuid = target; ExceptGuid = except; Payload = payload; }
            internal static Delivery To(string target, string payload) => new Delivery(target, null, payload);
            internal static Delivery Others(string except, string payload) => new Delivery(null, except, payload);
            internal static Delivery All(string payload) => new Delivery(null, null, payload);
        }

        public sealed class Rejected : Exception
        {
            public readonly string Code;
            public Rejected(string code) : base(code) { Code = code; }
        }

        public sealed class SceneInventory
        {
            public readonly string SpaceId;
            public readonly int GenericCount;
            public readonly bool Verified;
            public readonly bool ReplayGenericHistory;
            private readonly HashSet<int> boats, extensionCounts;
            private readonly HashSet<string> consumables;

            // Trusted host configuration only. Generic IDs are incremental
            // 0..N-1 from the loaded scene, never Unity serialized path IDs.
            // Native NebulaInteractor.ctor5df620 initializes the counter to -1;
            // AddGenericInteractable5deab0 increments before assigning the ID.
            // The host must exclude deferred game subtypes from a registry;
            // mixed game/non-game scenes need a proven ID map, not count alone.
            public SceneInventory(string spaceId, IEnumerable<int> boatTokens,
                IEnumerable<string> consumableTags, int genericCount = 0,
                IEnumerable<int> genericExtensionCounts = null, bool verified = true,
                bool replayGenericHistory = false)
            {
                if (String.IsNullOrEmpty(spaceId) || genericCount < 0 || genericCount > 4096)
                    throw new ArgumentException("invalid trusted scene inventory");
                SpaceId = spaceId; GenericCount = genericCount; Verified = verified;
                ReplayGenericHistory = replayGenericHistory;
                boats = new HashSet<int>(boatTokens ?? new int[0]);
                if (boats.Any(x => x < 0 || x > 4096)) throw new ArgumentException("invalid boat tokens");
                consumables = new HashSet<string>(consumableTags ?? new string[0], StringComparer.Ordinal);
                if (consumables.Any(x => x != "coffee" && x != "oktoberfest"))
                    throw new ArgumentException("unknown consumable tag");
                extensionCounts = new HashSet<int>(genericExtensionCounts ?? new[] { 0 });
                if (extensionCounts.Any(x => x < 0 || x > 32)) throw new ArgumentException("invalid extension counts");
            }

            public static SceneInventory ForSpace(string spaceId)
            {
                if (spaceId == null) throw new ArgumentNullException(nameof(spaceId));
                // Compare explicit shipped bundle/scene names case-insensitively.
                // These are local host identifiers, not invented commercial IDs.
                string key = spaceId.ToLowerInvariant();
                // HarbourEnter.boatPrefab[0..2] = Leaf Park Boat, Swan Boat,
                // Flamingo Boat. FOODTRUCK is active. All three OktoberFest
                // groups are inactive in the shipped prefab hierarchy.
                if (key == "leafpark") return new SceneInventory(spaceId,
                    new[] { 0, 1, 2 }, new[] { "coffee" });
                if (key == "beach" || key == "bluewavehideout" || key == "greenhouse")
                    return new SceneInventory(spaceId, new[] { 0 }, null);
                // Null-script base-only placeholders are not unknown subtypes.
                // TheNebulian has one active DayNightBasicCycle (ID0) and boat0.
                if (key == "thenebulian") return new SceneInventory(spaceId, new[] { 0 }, null, 1);
                switch (key)
                {
                    case "greeksummerhouse": case "nebuhouse": case "nebuhouseopenhouse":
                    case "serenegarden": case "woodlandclearing":
                        return new SceneInventory(spaceId, null, null, 1);
                    case "westvalleyapartment": case "westvalleyapartmentopenhouse": case "wintersnowglobe":
                        return new SceneInventory(spaceId, null, null, 2);
                    case "tokyoapartment": return new SceneInventory(spaceId, null, null, 3);
                    case "lechalet": case "whisperinghillsmansion":
                        return new SceneInventory(spaceId, null, null, 4);
                    case "lakeapartment": return new SceneInventory(spaceId, null, null, 6);
                    case "waterfall": return new SceneInventory(spaceId, null, null, 9);
                    case "hollyridgeestate":
                        // Decoration callbacks increment their own data[0] on
                        // each change. Replaying all accepted transitions keeps
                        // that local cycle aligned without assuming which Id it is.
                        return new SceneInventory(spaceId, null, null, 4, new[] { 0, 1 }, replayGenericHistory: true);
                    case "nexus": case "cinema": case "cliffapartment": case "cube":
                    case "deadquarters": case "dome": case "dressingroom": case "flyingdevice":
                    case "forgottenstation": case "ghosttown": case "gingerbreadhouse": case "home":
                    case "medievalvillage": case "mountainhideout": case "skl": case "starcrawlers":
                    case "steampunk": case "stonelakecastle": case "thecrypt": case "themoonlightroom":
                    case "tokyoapartmentopenhouse": case "windmillfarmhouse": case "zerodistrict": case "zerodistrictden":
                    case "bowling": case "thenebulianopenhouse":
                        return new SceneInventory(spaceId, null, null);
                    // Mixed game/non-game IDs cannot be filtered by static
                    // counts. Unresolved-script scenes also require a map.
                    case "campsilverlake": case "cutteridgeestate": case "sorcererseyrie":
                        return new SceneInventory(spaceId, null, null, verified: false);
                }
                // Unknown spaces are closed until a trusted registry is supplied.
                return new SceneInventory(spaceId, null, null, verified: false);
            }

            internal bool Boat(int token) => Verified && boats.Contains(token);
            internal bool Consumable(string tag) => Verified && consumables.Contains(tag);
            internal bool Generic(int id, int extras) => Verified && id >= 0 && id < GenericCount && extensionCounts.Contains(extras);
        }

        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
        private readonly SceneInventory inventory;
        private readonly Func<string, Identity> resolveIdentity;
        private readonly Func<Identity, string, string, int?> claimConsumable;
        private readonly Dictionary<string, int> boats = new Dictionary<string, int>(StringComparer.Ordinal);
        private readonly Dictionary<string, HashSet<string>> boatSnapshots = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        private readonly Dictionary<int, string> genericReplies = new Dictionary<int, string>();
        private readonly Dictionary<int, bool> genericStates = new Dictionary<int, bool>();
        private readonly List<string> genericHistory = new List<string>();
        private readonly HashSet<string> sceneSnapshots = new HashSet<string>(StringComparer.Ordinal);

        public bool ReadyForOriginalServerParity => false;
        public string SpaceId => inventory.SpaceId;
        public bool HasVerifiedInventory => inventory.Verified;
        public int GenericInteractableCount => inventory.GenericCount;
        public bool HasBoat(string guid) => guid != null && boats.ContainsKey(guid);

        // claimConsumable must atomically claim a durable HTTP-issued receipt
        // bound to actor.Guid, actor.PlatformId, tag and this instance/space.
        // It returns authoritative positive prop uses, never a client count.
        public NebulaWorldState(SceneInventory inventory, Func<string, Identity> resolveIdentity,
            Func<Identity, string, string, int?> claimConsumable = null)
        {
            this.inventory = inventory ?? throw new ArgumentNullException(nameof(inventory));
            this.resolveIdentity = resolveIdentity ?? throw new ArgumentNullException(nameof(resolveIdentity));
            this.claimConsumable = claimConsumable;
        }

        public bool Handles(int opcode) => opcode == 31 || (opcode >= 44 && opcode <= 47) || opcode == 93 || opcode == 94;

        // args exclude opcode and the AES-added C2S platform-name trailer.
        // The host binds the connection before calling this method. Broadcast
        // recipients must be announced actors in this same instance.
        public IReadOnlyList<Delivery> Handle(string callerGuid, int opcode, string[] args)
        {
            if (!Handles(opcode)) throw new Rejected("world_opcode_not_supported");
            if (args == null || args.Length == 0 || args[0] != callerGuid)
                throw new Rejected("world_session_not_owned");
            Identity caller = IdentityFor(callerGuid);
            if (opcode == 45 || opcode == 47 || opcode == 93)
                throw new Rejected("world_clientbound_only_opcode");
            if (opcode == 31) return Boat(caller, args);
            if (opcode == 94) return Generic(caller, args);
            return Consumable(caller, opcode, args);
        }

        private IReadOnlyList<Delivery> Boat(Identity caller, string[] args)
        {
            Count(args, 3);
            bool entering = BooleanValue(args[1]);
            int token = Integer(args[2]);
            if (!inventory.Boat(token)) throw new Rejected("boat_token_not_in_scene");
            if (!entering)
            {
                if (boats.TryGetValue(caller.Guid, out int prior) && prior != token)
                    throw new Rejected("boat_release_token_mismatch");
                boats.Remove(caller.Guid);
                ForgetActorSnapshots(caller.Guid);
                // S2C31 False is ignored by the shipped receiver. Local exit
                // already ran; do not invent a remote cleanup instruction.
                return new Delivery[0];
            }
            if (boats.TryGetValue(caller.Guid, out int current))
            {
                if (current != token) throw new Rejected("boat_change_requires_exit");
                return new Delivery[0]; // duplicate True would create remote clones
            }
            boats[caller.Guid] = token;
            ForgetActorSnapshots(caller.Guid);
            // The C2S caller already instantiated its own boat before sending.
            return new[] { Delivery.Others(caller.Guid, Join(31, caller.Guid, "True", token.ToString(Invariant))) };
        }

        private IReadOnlyList<Delivery> Generic(Identity caller, string[] args)
        {
            if (args.Length < 3) throw new Rejected("world_wrong_field_count");
            int id = Integer(args[1]);
            bool state = BooleanValue(args[2]);
            if (!inventory.Generic(id, args.Length - 3)) throw new Rejected("generic_interactable_not_in_scene");
            foreach (string extra in args.Skip(3)) Token(extra, 512);
            // All reviewed non-game prefab baselines have _isActive=false.
            // This is a bool relay: subtype data is not assigned from extensions
            // by the reviewed callbacks. Dynamic decoration replay is limited.
            bool old = genericStates.TryGetValue(id, out bool value) && value;
            if (old == state) return new Delivery[0];
            if (inventory.ReplayGenericHistory && genericHistory.Count >= 4096)
                throw new Rejected("generic_scene_history_limit");
            var fields = new List<string> { caller.Guid, id.ToString(Invariant), state ? "True" : "False" };
            fields.AddRange(args.Skip(3));
            string payload = Join(94, fields.ToArray());
            genericStates[id] = state;
            genericReplies[id] = payload;
            if (inventory.ReplayGenericHistory) genericHistory.Add(payload);
            // Unlike boat31, Generic.Interact only sends; sender needs callback.
            return new[] { Delivery.All(payload) };
        }

        private IReadOnlyList<Delivery> Consumable(Identity caller, int opcode, string[] args)
        {
            Count(args, 3);
            string tag = opcode == 44 ? "coffee" : "oktoberfest";
            if (args[1] != tag || !inventory.Consumable(tag)) throw new Rejected("consumable_not_in_scene");
            Token(args[2], 256);
            if (String.IsNullOrEmpty(args[2]) || claimConsumable == null)
                throw new Rejected("consumable_http_receipt_required");
            int? uses = claimConsumable(caller, tag, args[2]);
            if (!uses.HasValue || uses.Value <= 0) throw new Rejected("consumable_receipt_not_authorized");
            string count = uses.Value.ToString(Invariant);
            // Blank token1 is unread. The one-way OktoberFest packet alone
            // omits it; Coffee45 retains the same four-field layout as44.
            return new[] {
                Delivery.To(caller.Guid, Join(opcode, caller.Guid, "", tag, count)),
                Delivery.Others(caller.Guid, opcode == 44 ? Join(45, caller.Guid, "", tag, count) : Join(47, caller.Guid, tag, count))
            };
        }

        // Call only once after the requester has assembled the target avatar
        // (e.g. its post-build GetCurrentPosition20 query), never on early join.
        public IReadOnlyList<Delivery> SnapshotActor(string requesterGuid, string actorGuid)
        {
            IdentityFor(requesterGuid);
            IdentityFor(actorGuid);
            if (requesterGuid == actorGuid || !boats.TryGetValue(actorGuid, out int token)) return new Delivery[0];
            if (!boatSnapshots.TryGetValue(requesterGuid, out HashSet<string> seen))
            {
                seen = new HashSet<string>(StringComparer.Ordinal);
                boatSnapshots[requesterGuid] = seen;
            }
            if (!seen.Add(actorGuid)) return new Delivery[0];
            return new[] { Delivery.To(requesterGuid, Join(31, actorGuid, "True", token.ToString(Invariant))) };
        }

        // Ordinary94 has no distinct initial-query request. Replay only recorded
        // bool changes, once after the recipient's world objects initialize.
        public IReadOnlyList<Delivery> SnapshotScene(string requesterGuid)
        {
            IdentityFor(requesterGuid);
            if (!sceneSnapshots.Add(requesterGuid)) return new Delivery[0];
            if (inventory.ReplayGenericHistory)
                return genericHistory.Select(x => Delivery.To(requesterGuid, x)).ToArray();
            return genericReplies.OrderBy(x => x.Key).Select(x => Delivery.To(requesterGuid, x.Value)).ToArray();
        }

        public IReadOnlyList<Delivery> Disconnect(string guid)
        {
            boats.Remove(guid);
            boatSnapshots.Remove(guid);
            sceneSnapshots.Remove(guid);
            ForgetActorSnapshots(guid);
            return new Delivery[0];
        }

        private void ForgetActorSnapshots(string guid)
        { foreach (HashSet<string> actors in boatSnapshots.Values) actors.Remove(guid); }

        private Identity IdentityFor(string guid)
        {
            Token(guid, 256);
            Identity identity = resolveIdentity(guid);
            if (String.IsNullOrEmpty(guid) || identity == null || identity.Guid != guid || String.IsNullOrEmpty(identity.PlatformId))
                throw new Rejected("world_identity_not_current");
            return identity;
        }
        private static int Integer(string text)
        {
            if (!Int32.TryParse(text, NumberStyles.Integer, Invariant, out int value)) throw new Rejected("world_invalid_integer");
            return value;
        }
        private static bool BooleanValue(string text)
        {
            if (!Boolean.TryParse(text, out bool value)) throw new Rejected("world_invalid_boolean");
            return value;
        }
        private static void Count(string[] args, int count)
        { if (args.Length != count) throw new Rejected("world_wrong_field_count"); }
        private static void Token(string token, int max)
        { if (token == null || token.Length > max || token.IndexOf('#') >= 0 || token.IndexOf('\0') >= 0) throw new Rejected("world_invalid_token"); }
        private static string Join(int opcode, params string[] fields) => opcode.ToString(Invariant) + "#" + String.Join("#", fields);
    }
}
