using System;
using System.IO;
using System.Linq;
using UnityEngine;

namespace NebulaPreservation
{
    // Same-host operator-controlled IPC only. No sockets, credentials or SQLite.
    public sealed class NebulaResourceSelections
    {
        [Serializable] public sealed class Request
        {
            public int format_version = 1;
            public string request_id, guid, instance_id, instance_owner, kind, item_id;
            public long expected_revision;
            public double created_at, expires_at;
        }
        [Serializable] public sealed class Ack
        {
            public int format_version;
            public string request_id, guid, instance_id, instance_owner, kind, item_id, status, reason;
            public long expected_revision, revision;
        }
        private readonly string folder, instance, owner;
        public NebulaResourceSelections(string stateRoot, string instanceId, string instanceOwner)
        {
            if (String.IsNullOrEmpty(instanceId) || instanceId.Length > 128 ||
                instanceId.Any(c => !Char.IsLetterOrDigit(c) && c != '-' && c != '_'))
                throw new InvalidDataException("resource_selection_instance");
            instance = instanceId;
            if (instanceOwner == null || instanceOwner.Length != 32 || instanceOwner.Any(c => !(c >= '0' && c <= '9' || c >= 'a' && c <= 'f')))
                throw new InvalidDataException("resource_selection_owner");
            owner = instanceOwner;
            folder = Path.GetFullPath(Path.Combine(stateRoot, "instances", instance, "resource-selections"));
            CheckPath();
            Directory.CreateDirectory(folder);
        }
        private void CheckPath()
        {
            for (DirectoryInfo d = new DirectoryInfo(folder); d != null; d = d.Parent)
                if (d.Exists && (d.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("resource_selection_linked_path");
        }
        public Request Begin(string guid, string kind, string item, long revision, double now)
        {
            CheckPath();
            if (Directory.EnumerateFiles(folder, "*.request.json").Take(129).Count() >= 128)
                throw new InvalidDataException("resource_selection_capacity");
            var request = new Request { request_id = Guid.NewGuid().ToString("N"), guid = guid,
                instance_id = instance, instance_owner = owner, kind = kind, item_id = item, expected_revision = revision,
                created_at = now, expires_at = now + 15 };
            string path = Path.Combine(folder, request.request_id + ".request.json");
            string temporary = path + ".tmp";
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (var writer = new StreamWriter(stream, new System.Text.UTF8Encoding(false)))
                    writer.Write(JsonUtility.ToJson(request));
                File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
            return request;
        }
        public Ack Poll(Request request)
        {
            CheckPath();
            string path = Path.Combine(folder, request.request_id + ".ack.json");
            if (!File.Exists(path)) return null;
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0 || new FileInfo(path).Length > 4096)
                throw new InvalidDataException("resource_selection_ack_size_or_link");
            Ack ack;
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(stream)) ack = JsonUtility.FromJson<Ack>(reader.ReadToEnd());
            if (ack == null || ack.format_version != 1 || ack.request_id != request.request_id ||
                ack.guid != request.guid || ack.instance_id != instance || ack.instance_owner != owner || ack.kind != request.kind ||
                ack.item_id != request.item_id || ack.expected_revision != request.expected_revision ||
                (ack.status != "committed" && ack.status != "rejected") ||
                (ack.status == "committed" && (ack.reason != "" || ack.revision != request.expected_revision + 1)))
                throw new InvalidDataException("resource_selection_ack_binding");
            return ack;
        }
        public void Finish(Request request)
        {
            CheckPath();
            foreach (string suffix in new[] { ".request.json", ".ack.json" })
            {
                string path = Path.Combine(folder, request.request_id + suffix);
                if (File.Exists(path) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) == 0) File.Delete(path);
            }
        }
    }
}
