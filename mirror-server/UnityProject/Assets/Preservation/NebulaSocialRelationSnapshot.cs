using System;
using System.Collections.Generic;

namespace NebulaPreservation
{
    // Converts composite replacement-service state into the shipped client's
    // additive RelationshipUpdated (opcode 28) enum.
    public static class NebulaSocialRelationSnapshot
    {
        public struct State
        {
            public readonly bool Friend;
            public readonly bool Favorite;
            public readonly bool Ignored;
            public readonly bool SilentBy;
            public readonly bool BlockedUsers;
            public readonly bool UserBlockedBy;

            public State(bool friend = false, bool favorite = false, bool ignored = false,
                bool silentBy = false, bool blockedUsers = false, bool userBlockedBy = false)
            {
                Friend = friend;
                Favorite = favorite;
                Ignored = ignored;
                SilentBy = silentBy;
                BlockedUsers = blockedUsers;
                UserBlockedBy = userBlockedBy;
            }
        }

        public sealed class Plan
        {
            public readonly bool ReseedEntity;
            public readonly int[] Codes;

            internal Plan(bool reseedEntity, int[] codes)
            {
                ReseedEntity = reseedEntity;
                Codes = codes;
            }
        }

        // Block is a visibility boundary and retains the original conflict
        // priority. Silence remains directional, but friend/favorite flags are
        // still published because native codes 1 and 2 set independent bits.
        public static int[] Codes(State state)
        {
            if (state.BlockedUsers) return new[] {5};
            if (state.UserBlockedBy) return new[] {6};

            var result = new List<int>(3);
            if (state.Ignored) result.Add(3);
            else if (state.SilentBy) result.Add(4);
            if (state.Friend) result.Add(1);
            if (state.Favorite) result.Add(2);
            if (result.Count == 0) result.Add(0);
            return result.ToArray();
        }

        // Native code 0 clears friend/silence/block flags, but not favorite;
        // it also does not reactivate an avatar hidden by code 5/6 or restore
        // its removed interactable. Those transitions require a viewer-side
        // destroy/reseed rather than another opcode-28 value.
        public static Plan Transition(State previous, State next)
        {
            bool wasHidden = previous.BlockedUsers || previous.UserBlockedBy;
            bool isHidden = next.BlockedUsers || next.UserBlockedBy;
            bool reseed = (wasHidden && !isHidden) || (previous.Favorite && !next.Favorite);
            int[] desired = Codes(next);
            if (reseed) return new Plan(true, desired);

            bool removed = (previous.Friend && !next.Friend) ||
                (previous.Ignored && !next.Ignored) ||
                (previous.SilentBy && !next.SilentBy) ||
                (previous.BlockedUsers && !next.BlockedUsers) ||
                (previous.UserBlockedBy && !next.UserBlockedBy);
            if (!removed || (desired.Length == 1 && desired[0] == 0))
                return new Plan(false, desired);

            var resetThenDesired = new int[desired.Length + 1];
            resetThenDesired[0] = 0;
            Array.Copy(desired, 0, resetThenDesired, 1, desired.Length);
            return new Plan(false, resetThenDesired);
        }
    }
}
