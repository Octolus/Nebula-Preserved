using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace NebulaPreservation
{
    // Pure validation/translation for shipped C2S4 -> S2C5 animation frames.
    // Field1 is -1 for seats/emotes or the signed local Mirror netId for RandomIdle.Initialize.
    public static class NebulaAnimationWire
    {
        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;

        public sealed class Rejected : Exception
        {
            public readonly string Code;
            public Rejected(string code) : base(code) { Code = code; }
        }

        public static string BuildReply(string[] fields, uint ownedNetId)
        {
            if (fields == null || fields.Length < 6) throw new Rejected("invalid_animation_fields");
            int animationNetId = Integer(fields[1]);
            if (animationNetId != -1 && animationNetId != unchecked((int)ownedNetId)) throw new Rejected("invalid_animation_netid_sentinel");
            int type = Integer(fields[2]);
            int cycle = Integer(fields[3]);
            int count = Integer(fields[5]);
            if (type < 0 || type > 7 || cycle < 0 || cycle > 2 || count < 0 || count > 128 ||
                (count == 0 ? !(fields.Length == 7 && fields[6] == "") : fields.Length != 6 + count))
                throw new Rejected("invalid_animation_count_or_enum");
            var reply = new List<string> {fields[0], fields[2], fields[3], fields[4], fields[5]};
            reply.AddRange(fields.Skip(6));
            return "5#" + String.Join("#", reply.ToArray());
        }

        private static int Integer(string value)
        {
            if (!Int32.TryParse(value, NumberStyles.Integer, Invariant, out int result))
                throw new Rejected("invalid_int32");
            return result;
        }
    }
}
