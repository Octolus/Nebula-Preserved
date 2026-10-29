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
        private static readonly string[] publicScenes = { "Nexus", "LeafPark", "Beach", "Cinema" };
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

        public static bool Eligible(string profile, string space, bool listening,
            int boardTables, int dartsTables, bool sceneVerified, bool housingBound, bool semanticTrusted = false)
        {
            if (!listening || boardTables != 0 || dartsTables != 0) return false;
            if (profile == "nexus-core-v1") return space == "Nexus";
            if (profile == "nonmini-core-v1") return IsNonMiniScene(space) && sceneVerified &&
                (!IsPersonalSpace(space) || housingBound);
            return profile == "nonmini-semantic-v1" && IsSemanticNonMiniScene(space) && semanticTrusted &&
                (!IsPersonalSpace(space) || housingBound);
        }
    }
}
