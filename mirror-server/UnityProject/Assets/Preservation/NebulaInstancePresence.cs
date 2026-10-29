using System;
using System.Collections.Generic;
using System.Linq;

namespace NebulaPreservation
{
    // Real per-instance HTTP handoff DTO. The consumer binds directory name,
    // current allocation and scene; omitting either identity makes every
    // otherwise connected player appear offline to HTTP invite lookup.
    [Serializable]
    public sealed class NebulaInstancePresence
    {
        [Serializable] public sealed class Player { public string guid; public int status; }
        public int format_version = 1;
        public string instance_id, psidglobal;
        public double generation;
        public Player[] players;

        public NebulaInstancePresence(string instanceId, string spaceId, double now, IEnumerable<Player> present)
        {
            if (String.IsNullOrEmpty(instanceId) || String.IsNullOrEmpty(spaceId) ||
                Double.IsNaN(now) || Double.IsInfinity(now) || now < 0 || present == null)
                throw new ArgumentException("invalid_instance_presence");
            instance_id = instanceId; psidglobal = spaceId; generation = now;
            players = present.ToArray();
        }
    }
}
