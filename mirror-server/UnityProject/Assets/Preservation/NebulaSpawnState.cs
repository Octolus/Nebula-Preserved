using System;
using Mirror;
using UnityEngine;

namespace NebulaPreservation
{
    // Derived from the shipped prefab plus native deserializers. Does not load
    // the proprietary prefab or make the receive-only probe a game server.
    public static class NebulaSpawnState
    {
        public static readonly Guid PlayerAssetId = new Guid("86041873b099ede4687c67606e379683");

        public static byte[] Initial(Vector3 position, Quaternion rotation, float speed)
        {
            var writer = new NetworkWriter();
            // NetworkBehaviour0: disabled Mirror.NetworkTransform. Initial
            // state still serializes because NetworkIdentity ignores enabled.
            writer.WriteByte(0);
            writer.WriteInt(28);
            writer.WriteVector3(position);
            writer.WriteQuaternion(rotation);
            // NetworkBehaviour1: NebulaPlayerSyncVars. No SyncObjects; initial
            // syncvar state is speed only, without a dirty mask.
            writer.WriteByte(1);
            writer.WriteInt(4);
            writer.WriteFloat(speed);
            return writer.ToArray();
        }

        public static byte[] SpeedDelta(float speed)
        {
            var writer = new NetworkWriter();
            writer.WriteByte(1);
            writer.WriteInt(12);
            writer.WriteULong(1); // dirty bit0 = speed
            writer.WriteFloat(speed);
            return writer.ToArray();
        }
    }
}
