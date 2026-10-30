using System;
using System.IO;
using System.Text.Json;
using NebulaPreservation;

internal static class Program
{
    private static int passed;
    private static readonly NebulaSocialState.Actor A = new NebulaSocialState.Actor(
        new string('a', 32), "synthetic-a", "Synthetic A", "StandaloneWindows", 1);
    private static readonly NebulaSocialState.Actor B = new NebulaSocialState.Actor(
        new string('b', 32), "synthetic-b", "Synthetic B", "StandaloneWindows", 1);

    private static void Check(bool condition, string name)
    {
        if (!condition) throw new Exception("Social contract failed: " + name);
        passed++;
    }

    private sealed class Fixture : IDisposable
    {
        private readonly string parent;
        public readonly string Root;
        public readonly NebulaSocialState Social;
        public double Now = 1000;
        public Fixture(string parent)
        {
            this.parent = Path.TrimEndingDirectorySeparator(Path.GetFullPath(parent)) + Path.DirectorySeparatorChar;
            Root = Path.GetFullPath(Path.Combine(parent, "social-contract-" + Guid.NewGuid().ToString("N")));
            RequireScope();
            Directory.CreateDirectory(Root);
            Social = new NebulaSocialState(Root, () => Now);
        }
        private void RequireScope()
        {
            if (!Root.StartsWith(parent, StringComparison.Ordinal) || Root.Length <= parent.Length)
                throw new InvalidOperationException("Fixture path is outside its temporary parent");
        }
        public void Snapshot(bool friends, bool blocked = false)
        {
            // Each replacement is distinct even on filesystems with coarse mtimes.
            object[] rows = friends ? new object[] {
                new {ps4_id=A.AccountId, target=B.Username, target_platform=B.Platform, kind="friend"},
                new {ps4_id=B.AccountId, target=A.Username, target_platform=A.Platform, kind="friend"}
            } : Array.Empty<object>();
            if (blocked)
            {
                var expanded = new object[rows.Length + 1];
                rows.CopyTo(expanded, 0);
                expanded[rows.Length] = new {ps4_id=B.AccountId, target=A.Username, target_platform=A.Platform, kind="block"};
                rows = expanded;
            }
            File.WriteAllText(Path.Combine(Root, "instance-relations.json"),
                JsonSerializer.Serialize(new {format_version=1, generation=Now, relations=rows}));
        }
        public void AcceptFriend()
        {
            Social.Request(A, B, 1);
            Social.Accept(B, A, 1);
        }
        public void Dispose()
        {
            RequireScope();
            Directory.Delete(Root, true);
        }
    }

    private static int Main(string[] args)
    {
        try { Run(args); return 0; }
        catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
    }

    private static void Run(string[] args)
    {
        if (args.Length != 1 || !Directory.Exists(args[0]))
            throw new ArgumentException("Supply an existing temporary parent directory");

        using (var f = new Fixture(args[0]))
        {
            f.Snapshot(false); f.AcceptFriend();
            Check(f.Social.CanPrivateChat(A, B), "accepted event bridges the publication delay");
            f.Now += 14.999;
            Check(f.Social.Relation(A, B) == 1, "publication grace remains before the boundary");
            f.Now = 1015;
            Check(f.Social.Relation(A, B) == 0 && !f.Social.CanPrivateChat(A, B),
                "uncommitted acceptance expires at fifteen seconds without a snapshot rewrite");
            Check(Directory.GetFiles(Path.Combine(f.Root, "friend-events"), "*.json").Length == 1,
                "expiry retains the immutable event for the persistence authority");
        }
        using (var f = new Fixture(args[0]))
        {
            f.AcceptFriend(); f.Now += 16;
            Check(!f.Social.CanPrivateChat(A, B), "missing snapshot cannot preserve an expired friendship grant");
        }
        using (var f = new Fixture(args[0]))
        {
            f.Snapshot(false); f.AcceptFriend(); f.Now += 1; f.Snapshot(true);
            Check(f.Social.Relation(A, B) == 1, "durable reciprocal acceptance supersedes the overlay");
            f.Now += 100;
            Check(f.Social.CanPrivateChat(A, B), "committed friendship survives overlay expiry");
        }
        using (var f = new Fixture(args[0]))
        {
            f.Snapshot(true);
            Check(f.Social.CanPrivateChat(A, B), "initial durable friendship permits chat");
            f.Social.RemoveFriendship(A, B);
            Check(!f.Social.CanPrivateChat(A, B), "removal hides friendship while awaiting publication");
            f.Now += 15;
            Check(f.Social.CanPrivateChat(A, B), "uncommitted removal eventually returns to durable state");
        }
        using (var f = new Fixture(args[0]))
        {
            f.Snapshot(true); f.Social.RemoveFriendship(A, B); f.Now += 1; f.Snapshot(false);
            Check(!f.Social.CanPrivateChat(A, B), "durable removal retires its optimistic overlay");
            f.Now += 100;
            Check(f.Social.Relation(A, B) == 0, "committed removal stays removed after the grace period");
        }
        using (var f = new Fixture(args[0]))
        {
            f.Snapshot(false); f.Social.ObserveFriendship(A, B);
            Check(f.Social.CanPrivateChat(A, B), "cross-instance friendship notice bridges publication");
            f.Now += 15;
            Check(!f.Social.CanPrivateChat(A, B), "cross-instance notice does not grant indefinite chat authority");
        }
        using (var f = new Fixture(args[0]))
        {
            f.Snapshot(false, blocked: true); f.Social.ObserveFriendship(A, B);
            Check(!f.Social.CanPrivateChat(A, B), "optimistic friendship never bypasses durable blocking");
        }
        using (var f = new Fixture(args[0]))
        {
            f.Snapshot(false); f.Social.Request(A, B, 0); f.Social.Accept(B, A, 0);
            f.Now += 16;
            Check(f.Social.CanPrivateChat(A, B), "explicit private-chat consent has its separate recovered local lifetime");
            f.Social.Disconnect(A.Guid);
            Check(!f.Social.CanPrivateChat(A, B), "session invalidation still retires explicit private-chat consent");
        }
        Console.WriteLine(JsonSerializer.Serialize(new {
            kind="authored_csharp_social_contracts_with_synthetic_json", passed,
            failed=0, game_launched=false, listeners_started=false, native_unity_json_executed=false
        }));
    }
}
