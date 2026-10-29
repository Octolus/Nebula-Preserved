using System;
using System.IO;
using System.Text;
using Mirror;
using UnityEngine;

// The full type name is part of Mirror's wire message ID. Keep this global.
public struct NebulaMessage : NetworkMessage
{
    public string data;
}

public sealed class NebulaMirrorProbe : MonoBehaviour
{
    [Serializable]
    private sealed class Entry
    {
        public string utc;
        public string kind;
        public int connection;
        public int channel;
        public bool authenticated;
        public string data;
    }

    private StreamWriter journal;
    private bool started;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Bootstrap()
    {
#if !UNITY_EDITOR
        if (Array.IndexOf(Environment.GetCommandLineArgs(), "--nebula-instance") >= 0)
            return;
        var go = new GameObject("Nebula preservation protocol probe");
        DontDestroyOnLoad(go);
        go.AddComponent<NebulaMirrorProbe>();
#endif
    }

    private void Start()
    {
        string[] args = Environment.GetCommandLineArgs();
        if (Array.IndexOf(args, "--nebula-listen") < 0)
        {
            Debug.Log("Listener disabled. Pass --nebula-listen explicitly to run the protocol probe.");
            Application.Quit(0);
            return;
        }

        ushort port = 28000;
        int portIndex = Array.IndexOf(args, "--nebula-port");
        if (portIndex >= 0 && (portIndex + 1 >= args.Length || !ushort.TryParse(args[portIndex + 1], out port) || port == 0))
        {
            Debug.LogError("--nebula-port must be an integer from 1 through 65535.");
            Application.Quit(2);
            return;
        }

        string directory = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Logs"));
        Directory.CreateDirectory(directory);
        string path = Path.Combine(directory, "nebula-mirror-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + ".jsonl");
        journal = new StreamWriter(path, true, new UTF8Encoding(false)) { AutoFlush = true };
        Application.runInBackground = true;
        Application.targetFrameRate = 30;

        // Explicit assignment also avoids depending on discovery of the custom
        // message by the historic Weaver. Mirror's own serializers stay upstream.
        Writer<NebulaMessage>.write = (writer, value) => writer.WriteString(value.data);
        Reader<NebulaMessage>.read = reader => new NebulaMessage { data = reader.ReadString() };

        var transport = gameObject.AddComponent<TelepathyTransport>();
        transport.port = port;
        Transport.activeTransport = transport;
        NetworkServer.OnConnectedEvent += connection => Write("connected", connection, 0, null);
        NetworkServer.OnDisconnectedEvent += connection => Write("disconnected", connection, 0, null);
        NetworkServer.RegisterHandler<NebulaMessage>((connection, message, channel) =>
            Write("NebulaMessage", connection, channel, message.data), requireAuthentication: false);

        NetworkServer.Listen(32);
        started = true;
        Write("listening", null, 0, "127.0.0.1:" + port);
        Debug.Log("Nebula Mirror protocol probe listening on IPv4 loopback port " + port + ". Journal: " + path);
        Debug.Log("NebulaMessage ID=" + MessagePacking.GetId<NebulaMessage>() + "; no application replies are configured.");
    }

    private void Write(string kind, NetworkConnectionToClient connection, int channel, string data)
    {
        journal?.WriteLine(JsonUtility.ToJson(new Entry
        {
            utc = DateTime.UtcNow.ToString("O"),
            kind = kind,
            connection = connection != null ? connection.connectionId : 0,
            channel = channel,
            authenticated = connection != null && connection.isAuthenticated,
            data = data
        }));
    }

    private void OnApplicationQuit()
    {
        if (started)
            NetworkServer.Shutdown();
        journal?.Dispose();
        journal = null;
    }
}
