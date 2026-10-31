using System;
using System.Collections.Generic;
using System.Linq;
using NebulaPreservation;

// Wire contracts of the pure NebulaWorldState policy for C2S/S2C 93
// (UpdateAnimationLayer) and the unchanged neighbours it shares a host with.
internal static class Program
{
    private static int passed;
    private static readonly string A = new string('a', 32), B = new string('b', 32);
    private static readonly Dictionary<string, NebulaWorldState.Identity> People =
        new Dictionary<string, NebulaWorldState.Identity>
        {
            [A] = new NebulaWorldState.Identity(A, "Alice", "ps-a"),
            [B] = new NebulaWorldState.Identity(B, "Bob", "ps-b"),
        };

    private static void Check(bool condition, string name)
    {
        if (!condition) throw new Exception("World contract failed: " + name);
        passed++;
    }

    private static NebulaWorldState New(string space) => new NebulaWorldState(
        NebulaWorldState.SceneInventory.ForSpace(space), guid => People.TryGetValue(guid, out var p) ? p : null);

    private static IReadOnlyList<NebulaWorldState.Delivery> Run(NebulaWorldState state, string guid, int opcode,
        params string[] rest) => state.Handle(guid, opcode, new[] { guid }.Concat(rest).ToArray());

    private static string Rejects(Action action)
    {
        try { action(); }
        catch (NebulaWorldState.Rejected error) { return error.Code; }
        return null;
    }

    private static void Main()
    {
        // Cupid2018WalkingInLove 0x556f20/0x5572d0 and
        // Halloween2018ZombiesTrigger 0x5952a0/0x595650 send
        // 93#SessionGUID#InLove|Zombie#1|0. S2C93 0x5ec380 reads the same
        // three tokens, so the relay is the request minus the trailer.
        var world = New("MedievalVillage");
        Check(world.Handles(93), "93 handled");
        var output = Run(world, A, 93, "InLove", "1");
        Check(output.Count == 1 && output[0].TargetGuid == null && output[0].ExceptGuid == A &&
              output[0].Payload == "93#" + A + "#InLove#1", "93 relayed to others only, exact layout");
        Check(world.SnapshotActor(B, A).Select(d => d.TargetGuid + "|" + d.Payload).SequenceEqual(
            new[] { B + "|93#" + A + "#InLove#1" }), "late loader receives the active layer");
        Check(world.SnapshotActor(B, A).Count == 1, "layer replays on every fresh avatar build");
        Check(world.SnapshotActor(A, A).Count == 0, "no self snapshot");
        output = Run(world, A, 93, "InLove", "0");
        Check(output.Single().Payload == "93#" + A + "#InLove#0", "stop relayed");
        Check(world.SnapshotActor(B, A).Count == 0, "stopped layer is not replayed");

        Run(world, A, 93, "Zombie", "1");
        Run(world, A, 93, "InLove", "1");
        Check(world.SnapshotActor(B, A).Select(d => d.Payload).SequenceEqual(new[] {
            "93#" + A + "#InLove#1", "93#" + A + "#Zombie#1" }), "both layers replay in stable order");
        world.Disconnect(A);
        Check(world.SnapshotActor(B, A).Count == 0, "disconnect clears layers");

        Check(Rejects(() => Run(world, A, 93, "Swimming", "1")) == "animation_layer_not_supported", "unknown layer");
        Check(Rejects(() => Run(world, A, 93, "InLove", "0.5")) == "animation_layer_weight_invalid", "fractional weight");
        Check(Rejects(() => Run(world, A, 93, "InLove", "2")) == "animation_layer_weight_invalid", "weight out of range");
        Check(Rejects(() => Run(world, A, 93, "InLove")) == "world_wrong_field_count", "two fields");
        Check(Rejects(() => Run(world, A, 93, "InLove", "1", "x")) == "world_wrong_field_count", "four fields");
        Check(Rejects(() => world.Handle(A, 93, new[] { B, "InLove", "1" })) == "world_session_not_owned", "foreign guid");

        // 45 and 47 stay clientbound-only.
        Check(Rejects(() => Run(world, A, 45, "", "coffee", "1")) == "world_clientbound_only_opcode", "45 clientbound");
        Check(Rejects(() => Run(world, A, 47, "oktoberfest", "1")) == "world_clientbound_only_opcode", "47 clientbound");

        // A boat snapshot and a layer replay coexist in one actor snapshot.
        var harbour = New("LeafPark");
        Run(harbour, A, 31, "True", "1");
        Run(harbour, A, 93, "Zombie", "1");
        Check(harbour.SnapshotActor(B, A).Select(d => d.Payload).SequenceEqual(new[] {
            "31#" + A + "#True#1", "93#" + A + "#Zombie#1" }), "boat then layer");
        Check(harbour.SnapshotActor(B, A).Select(d => d.Payload).SequenceEqual(new[] {
            "93#" + A + "#Zombie#1" }), "boat snapshot stays once-only, layer replays");

        // Legacy 94 still goes to everyone (host no longer gates it on loadedRemotes).
        var waterfall = New("Waterfall");
        output = Run(waterfall, A, 94, "4", "True");
        Check(output.Single().TargetGuid == null && output.Single().ExceptGuid == null &&
              output.Single().Payload == "94#" + A + "#4#True", "94 broadcast to all");

        LocomotionEchoes();
        Console.WriteLine("World contracts passed: " + passed);
    }

    // C2S15 empty-frame accounting (NebulaLocomotionEchoes). "Applied" means the
    // host treats the frame as a real request; "dropped" means side effect.
    private static void LocomotionEchoes()
    {
        const string L = "LocoA", M = "LocoB", J = "GqOXf5oeSNwLL2W718G45L4s222EyKk5";
        double t = 1000;

        // Wheel A->B: OnClick 0x4b9be0 sends B, then UpdateLocomotion(B)
        // removes A and sends one empty in the same frame.
        var e = new NebulaLocomotionEchoes();
        e.Sent(A, A, L, t);                       // announce: own model unknown -> one receipt echo
        Check(e.ClientRequest(A, "", t + 0.1), "login receipt echo dropped");
        Check(!e.ClientRequest(A, M, t + 5), "wheel B applied");
        Check(e.ClientRequest(A, "", t + 5), "wheel A->B side-effect empty dropped");
        Check(e.Pending(A, t + 5) == 0, "nothing left to drop");

        // Wheel "none" (isEmpty entry): explicit empty, then the side effect.
        Check(!e.ClientRequest(A, "", t + 10), "explicit none applied");
        Check(e.ClientRequest(A, "", t + 10), "none side-effect empty dropped");
        Check(!e.ClientRequest(A, "", t + 20), "none without a locomotion applied (no side effect)");
        Check(e.Pending(A, t + 20) == 0, "no echo expected after removal from nothing");

        // Bare RemoveLocomotion removal (emote, Cupid, Zombie, coffee...):
        // applied; the unused own expectation expires within OwnWindow.
        Check(!e.ClientRequest(A, L, t + 30), "select L");
        var f = new NebulaLocomotionEchoes();
        f.Sent(B, B, "", t);                      // own model known empty after a receipt
        f.ClientRequest(B, "", t + 0.01);         // consumes the unknown-model receipt echo
        Check(!f.ClientRequest(B, L, t + 10), "B selects L from nothing");
        Check(f.Pending(B, t + 10) == 0, "no side effect when nothing was equipped");
        Check(!f.ClientRequest(B, "", t + 20), "emote removal applied");
        Check(f.Pending(B, t + 20 + NebulaLocomotionEchoes.OwnWindow + 0.01) == 0, "unused own expectation expires");
        Check(!f.ClientRequest(B, "", t + 21), "later genuine removal is not swallowed");

        // Viewer-origin: UpdateLocomotionProcessor 0x5ec4d0 on a remote with a
        // locomotion object makes the viewer send 15#<viewer>#.
        var v = new NebulaLocomotionEchoes();
        v.ActorBuilt(B, A);                       // fresh remote avatar: no object
        v.Sent(B, A, L, t);                       // 16 reply / first relay
        Check(v.Pending(B, t) == 0, "no echo from a remote without an object");
        v.Sent(B, A, M, t + 5);                   // A switches L -> M
        Check(v.Pending(B, t + 5) == 1, "relay over an existing remote object expects one echo");
        Check(v.ClientRequest(B, "", t + 5.2), "viewer-origin empty dropped");
        Check(!v.ClientRequest(B, "", t + 9), "viewer's own later removal applied");
        v.Sent(B, A, "", t + 20);
        Check(v.Pending(B, t + 20 + NebulaLocomotionEchoes.ReceiptWindow + 0.01) == 0, "receipt expectation expires");
        v.ActorRemoved(B, A);
        v.Sent(B, A, L, t + 40);                  // unknown remote model: expect conservatively
        Check(v.Pending(B, t + 40) == 1, "unknown remote model expects one echo");
        v.Forget(B);
        Check(v.Pending(B, t + 40) == 0, "disconnect forgets the client");

        // Jetpack flight (0x420090 -> 0x41fa00) with locomotion L equipped.
        var j = new NebulaLocomotionEchoes();
        j.Sent(A, A, L, t); j.ClientRequest(A, "", t + 0.1); // login with L applied locally
        Check(!j.ClientRequest(A, "", t + 10), "DisableLocomotionAndCompanion removal applied");
        Check(!j.ClientRequest(A, J, t + 10), "jetpack applied");
        Check(!j.ClientRequest(A, L, t + 60), "landing restore applied");
        Check(j.ClientRequest(A, "", t + 60), "landing UpdateLocomotion side-effect empty dropped");
        Check(j.Pending(A, t + 61) == 0, "flight leaves nothing pending");
        // AttachJetPack 0x41f200 while L is equipped: JET then one side effect.
        Check(!j.ClientRequest(A, J, t + 70), "attach jetpack applied");
        Check(j.ClientRequest(A, "", t + 70), "attach side-effect empty dropped");
    }
}
