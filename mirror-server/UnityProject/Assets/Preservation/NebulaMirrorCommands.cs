using System;
using Mirror;
using UnityEngine;

namespace NebulaPreservation
{
    // Native-derived command envelope only. Ownership and replacement server
    // behavior belong to the instance; recognizing a hash does not authorize it.
    public static class NebulaMirrorCommands
    {
        public const string SpeedSignature = "System.Void Assets.Scripts.NebulaPlayers.NebulaPlayerSyncVars::SetSpeed(System.Single)";
        public static readonly int SpeedHash = SpeedSignature.GetStableHashCode();
        public const string SyncSignature = "System.Void Mirror.NetworkTransformBase::CmdClientToServerSync(System.Nullable`1<UnityEngine.Vector3>,System.Nullable`1<UnityEngine.Quaternion>,System.Nullable`1<UnityEngine.Vector3>)";
        public const string TeleportSignature = "System.Void Mirror.NetworkTransformBase::CmdTeleport(UnityEngine.Vector3)";
        public const string TeleportRotationSignature = "System.Void Mirror.NetworkTransformBase::CmdTeleport(UnityEngine.Vector3,UnityEngine.Quaternion)";
        public const string LegacyTeleportSignature = "System.Void Mirror.NetworkTransformBase::CmdTeleportAndRotate(UnityEngine.Vector3,UnityEngine.Quaternion)";
        public static readonly int SyncHash = SyncSignature.GetStableHashCode();
        public static readonly int TeleportHash = TeleportSignature.GetStableHashCode();
        public static readonly int TeleportRotationHash = TeleportRotationSignature.GetStableHashCode();
        public static readonly int LegacyTeleportHash = LegacyTeleportSignature.GetStableHashCode();
        private static readonly int SyncRpcHash = "System.Void Mirror.NetworkTransformBase::RpcServerToClientSync(System.Nullable`1<UnityEngine.Vector3>,System.Nullable`1<UnityEngine.Quaternion>,System.Nullable`1<UnityEngine.Vector3>)".GetStableHashCode();
        private static readonly int TeleportRpcHash = "System.Void Mirror.NetworkTransformBase::RpcTeleport(UnityEngine.Vector3)".GetStableHashCode();
        private static readonly int TeleportRotationRpcHash = "System.Void Mirror.NetworkTransformBase::RpcTeleport(UnityEngine.Vector3,UnityEngine.Quaternion)".GetStableHashCode();

        public struct TransformCommand
        {
            public Vector3? position;
            public Quaternion? rotation;
            public Vector3? scale;
            public int rpcHash;
            public int channel;
            public ArraySegment<byte> payload;
        }

        public static bool IsSpeed(CommandMessage message)
        {
            return message.componentIndex == 1 && message.functionHash == SpeedHash;
        }

        public static bool TryReadSpeed(CommandMessage message, out float speed)
        {
            speed = 0;
            if (!IsSpeed(message) || message.payload.Array == null || message.payload.Count != 4)
                return false;
            var reader = new NetworkReader(message.payload);
            speed = reader.ReadFloat();
            return !Single.IsNaN(speed) && !Single.IsInfinity(speed);
        }

        public static bool IsTransform(CommandMessage message)
        {
            return message.componentIndex == 0 && (message.functionHash == SyncHash ||
                message.functionHash == TeleportHash || message.functionHash == TeleportRotationHash ||
                message.functionHash == LegacyTeleportHash);
        }

        public static bool TryReadTransform(CommandMessage message, out TransformCommand command)
        {
            command = default;
            if (!IsTransform(message) || message.payload.Array == null) return false;
            var reader = new NetworkReader(message.payload);
            var result = new TransformCommand {payload = message.payload};
            try
            {
                if (message.functionHash == SyncHash)
                {
                    if (Present(reader)) result.position = reader.ReadVector3();
                    if (Present(reader)) result.rotation = reader.ReadQuaternion();
                    if (Present(reader)) result.scale = reader.ReadVector3();
                    result.rpcHash = SyncRpcHash;
                    result.channel = Channels.Unreliable;
                }
                else
                {
                    result.position = reader.ReadVector3();
                    bool withRotation = message.functionHash != TeleportHash;
                    if (withRotation) result.rotation = reader.ReadQuaternion();
                    // The obsolete CmdTeleportAndRotate native body shares the
                    // non-obsolete two-argument teleport implementation.
                    result.rpcHash = withRotation ? TeleportRotationRpcHash : TeleportRpcHash;
                    result.channel = Channels.Reliable;
                }
                if (reader.Remaining != 0 ||
                    (result.position.HasValue && !Finite(result.position.Value)) ||
                    (result.rotation.HasValue && !ValidRotation(result.rotation.Value)) ||
                    (result.scale.HasValue && !Finite(result.scale.Value))) return false;
                command = result;
                return true;
            }
            catch (ArgumentException) { return false; }
            catch (System.IO.EndOfStreamException) { return false; }
            catch (IndexOutOfRangeException) { return false; }
        }

        private static bool Present(NetworkReader reader)
        {
            byte flag = reader.ReadByte();
            if (flag > 1) throw new ArgumentException("Invalid nullable flag");
            return flag == 1;
        }

        private static bool Finite(float x) => !Single.IsNaN(x) && !Single.IsInfinity(x);
        private static bool Finite(Vector3 v) => Finite(v.x) && Finite(v.y) && Finite(v.z);
        private static bool ValidRotation(Quaternion q) => Finite(q.x) && Finite(q.y) && Finite(q.z) && Finite(q.w) &&
            (double)q.x * q.x + (double)q.y * q.y + (double)q.z * q.z + (double)q.w * q.w > 0.000001;
    }
}
