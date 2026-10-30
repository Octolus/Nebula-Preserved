// Test substitute only: never included in the Unity Assets/player build.
// These contracts execute the authored social class, not native Unity JSON or UI.
namespace UnityEngine
{
    public static class JsonUtility
    {
        private static readonly System.Text.Json.JsonSerializerOptions options =
            new System.Text.Json.JsonSerializerOptions { IncludeFields = true };
        public static string ToJson<T>(T value) => System.Text.Json.JsonSerializer.Serialize(value, options);
        public static T FromJson<T>(string value) => System.Text.Json.JsonSerializer.Deserialize<T>(value, options);
    }
}
