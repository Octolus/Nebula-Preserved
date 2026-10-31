using System;
using System.Collections.Generic;

namespace NebulaPreservation
{
    // Explicit validation scopes, not original-service parity or production readiness.
    // Exact shipped navigator names: protocol/http-nonminigame-gap-audit.json.
    public static class NebulaCoreReadiness
    {
        private static readonly string[] personal = {
            "Home", "Greenhouse", "Waterfall", "StarCrawlers", "BlueWaveHideout", "DressingRoom",
            "CutteridgeEstate", "TheMoonlightRoom", "LeChalet", "LakeApartment", "SereneGarden",
            "WoodlandClearing", "TheNebulian", "SorcerersEyrie", "ZeroDistrictDen", "CampSilverLake",
            "FlyingDevice", "Deadquarters", "HollyridgeEstate", "WinterSnowGlobe", "TokyoApartment",
            "NebuHouse", "WestValleyApartment", "WhisperingHillsMansion", "CliffApartment", "TheCrypt",
            "ForgottenStation", "GreekSummerHouse", "MountainHideout", "GingerbreadHouse", "WindMillFarmHouse"
        };
        // Shipped public destinations: PreInitLOAD.NavigatorPublicSpaces plus the
        // Nexus Cinema/SKL triggers. SteamPunk is excluded: no s/steampunk scene bundle ships.
        private static readonly string[] publicScenes = {
            "Nexus", "LeafPark", "Beach", "Cinema", "Bowling", "Dome", "StoneLakeCastle", "Cube",
            "GhostTown", "TheNebulianOpenHouse", "ZeroDistrict", "NebuHouseOpenHouse",
            "WestValleyApartmentOpenHouse", "MedievalVillage", "SKL"
        };
        private static readonly HashSet<string> personalSet = new HashSet<string>(personal, StringComparer.Ordinal);
        private static readonly HashSet<string> publicSet = new HashSet<string>(publicScenes, StringComparer.Ordinal);
        private static readonly HashSet<string> mixed = new HashSet<string>(new[] {
            "CampSilverLake", "CutteridgeEstate", "SorcerersEyrie", "SorcerersEyrie1"
        }, StringComparer.Ordinal);

        public static string[] PersonalSpaceNames => (string[])personal.Clone();
        public static string[] PublicSceneNames => (string[])publicScenes.Clone();
        public static bool IsPersonalSpace(string space) => space != null &&
            (personalSet.Contains(space) || space == "SorcerersEyrie1");
        public static bool IsNonMiniScene(string space) => space != null &&
            (publicSet.Contains(space) || (personalSet.Contains(space) && !mixed.Contains(space)));
        public static bool IsSemanticNonMiniScene(string space) => space != null &&
            (publicSet.Contains(space) || personalSet.Contains(space) || space == "SorcerersEyrie1");

        // Shipped minigame managers, read-only from the scene bundles; each
        // count is the manager's gameTables length (client table/lane ids are
        // 0..count-1). Order: board, darts, pool, bowling.
        // StoneLakeCastleLogicPREFAB: BoardGamesManager with Table00..Table07.
        // BowlingLogicPREFAB: PoolGameManager GAME_00..08 (6..8 have inactive
        // parents), BowlingGameManager LANE_00..11, DartsGameManager
        // TABLE_00..02 under the inactive DARTS object (unreachable as shipped).
        // Every other scene has none.
        public static int[] SceneTables(string space)
        {
            if (space == "StoneLakeCastle") return new[] { 8, 0, 0, 0 };
            if (space == "Bowling") return new[] { 0, 3, 9, 12 };
            return new[] { 0, 0, 0, 0 };
        }

        public static bool SceneTablesMatch(string space, int boardTables, int dartsTables, int poolTables, int bowlingLanes)
        {
            int[] expected = SceneTables(space);
            return boardTables == expected[0] && dartsTables == expected[1] &&
                poolTables == expected[2] && bowlingLanes == expected[3];
        }

        public static bool Eligible(string profile, string space, bool listening,
            int boardTables, int dartsTables, int poolTables, int bowlingLanes,
            bool sceneVerified, bool housingBound, bool semanticTrusted = false)
        {
            if (!listening || !SceneTablesMatch(space, boardTables, dartsTables, poolTables, bowlingLanes)) return false;
            if (profile == "nexus-core-v1") return space == "Nexus";
            if (profile == "nonmini-core-v1") return IsNonMiniScene(space) && sceneVerified &&
                (!IsPersonalSpace(space) || housingBound);
            return profile == "nonmini-semantic-v1" && IsSemanticNonMiniScene(space) && semanticTrusted &&
                (!IsPersonalSpace(space) || housingBound);
        }
    }
}
