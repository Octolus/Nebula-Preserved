using System;
using System.IO;
using System.Security.Cryptography;
using UnityEngine;

// Editor-only adapter: the original builder remains the BuildReport authority.
public static class PreservationCIBuild
{
    [Serializable] public class Source { public string path; public string sha256; }
    [Serializable] public class Preparation
    {
        public int format_version; public string nonce; public string unity_editor;
        public Source[] source_hashes; public string wrapper_sha256; public string build_helper_sha256;
    }
    [Serializable] public class Receipt
    {
        public int format_version = 1; public string nonce; public string preparation_sha256;
        public string unity_editor; public Source[] source_hashes_before; public Source[] source_hashes_after;
        public string wrapper_sha256; public string success_marker; public bool marker_observed; public bool original_returned;
    }
    static string Hash(string path)
    {
        using (var stream = File.OpenRead(path)) using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }
    static Source[] HashSources(string root, Source[] rows)
    {
        if (rows == null || rows.Length != 21) throw new Exception("Expected 21 prepared sources");
        var result = new Source[rows.Length];
        for (int i = 0; i < rows.Length; ++i)
        {
            string path = Path.GetFullPath(Path.Combine(root, rows[i].path));
            if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal)) throw new Exception("Source outside root");
            result[i] = new Source { path = rows[i].path, sha256 = Hash(path) };
            if (result[i].sha256 != rows[i].sha256) throw new Exception("Prepared source changed");
        }
        return result;
    }
    public static void BuildLinuxServer()
    {
        string project = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
        string root = Path.GetFullPath(Path.Combine(project, ".."));
        string prepared = Path.Combine(root, "ci-source-before.json"), output = Path.Combine(root, "ci-build-receipt.json");
        if (File.Exists(output) || Directory.Exists(Path.Combine(root, "build-linux"))) throw new Exception("CI output already exists");
        var prep = JsonUtility.FromJson<Preparation>(File.ReadAllText(prepared));
        if (prep.format_version != 1 || prep.unity_editor != Application.unityVersion) throw new Exception("Wrong CI editor/preparation");
        string wrapper = Path.Combine(project, "Assets/Editor/PreservationCIBuild.cs");
        if (Hash(wrapper) != prep.wrapper_sha256) throw new Exception("CI wrapper changed");
        const string marker = "NEBULA_LINUX_SERVER_BUILD_SUCCESS";
        var receipt = new Receipt { nonce = prep.nonce, preparation_sha256 = Hash(prepared), unity_editor = Application.unityVersion,
            source_hashes_before = HashSources(root, prep.source_hashes), wrapper_sha256 = prep.wrapper_sha256 };
        string expected = marker + " " + Path.Combine(root, "build-linux", "NebulaServer.x86_64");
        Application.LogCallback observe = (message, stack, type) => { if (type == LogType.Log && message == expected) receipt.marker_observed = true; };
        string cwd = Directory.GetCurrentDirectory();
        Application.logMessageReceived += observe;
        try
        {
            Directory.SetCurrentDirectory(project);
            PreservationBuild.BuildLinuxServer(); // Throws unless the original BuildReport succeeded.
            receipt.original_returned = true;
            if (!receipt.marker_observed) throw new Exception("Original success marker was not observed");
            receipt.source_hashes_after = HashSources(root, prep.source_hashes);
            if (Hash(wrapper) != prep.wrapper_sha256 || Hash(prepared) != receipt.preparation_sha256) throw new Exception("CI inputs changed");
            receipt.success_marker = marker;
            using (var stream = new FileStream(output, FileMode.CreateNew, FileAccess.Write))
            using (var writer = new StreamWriter(stream)) writer.Write(JsonUtility.ToJson(receipt, true));
        }
        finally { Application.logMessageReceived -= observe; Directory.SetCurrentDirectory(cwd); }
    }
}
