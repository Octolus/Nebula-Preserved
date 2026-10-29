using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine.SceneManagement;

public static class PreservationBuild
{
    public static void Build()
    {
        BuildFor(BuildTarget.StandaloneWindows64, StandaloneBuildSubtarget.Player,
            "build", "NebulaMirrorProbe.exe", "NEBULA_PROBE_BUILD_SUCCESS");
    }

    public static void BuildLinuxServer()
    {
        BuildFor(BuildTarget.StandaloneLinux64, StandaloneBuildSubtarget.Server,
            "build-linux", "NebulaServer.x86_64", "NEBULA_LINUX_SERVER_BUILD_SUCCESS");
    }

    private static void BuildFor(BuildTarget target, StandaloneBuildSubtarget subtarget,
        string directory, string filename, string successMarker)
    {
        if (!BuildPipeline.IsBuildTargetSupported(BuildTargetGroup.Standalone, target))
            throw new Exception("Required Unity platform module is not installed: " + target);
        string scenePath = "Assets/Preservation/Probe.unity";
        Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        EditorSceneManager.SaveScene(scene, scenePath);
        PlayerSettings.companyName = "Nebula Preservation";
        PlayerSettings.productName = "Nebula Mirror Protocol Probe";
        PlayerSettings.runInBackground = true;
        var namedTarget = subtarget == StandaloneBuildSubtarget.Server
            ? UnityEditor.Build.NamedBuildTarget.Server : UnityEditor.Build.NamedBuildTarget.Standalone;
        PlayerSettings.SetScriptingBackend(namedTarget, ScriptingImplementation.Mono2x);
        string output = Path.GetFullPath(Path.Combine("..", directory, filename));
        Directory.CreateDirectory(Path.GetDirectoryName(output));
        BuildReport report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = new[] { scenePath },
            locationPathName = output,
            target = target,
            subtarget = (int)subtarget,
            options = BuildOptions.None
        });
        if (report.summary.result != BuildResult.Succeeded)
            throw new Exception("Mirror server build failed: " + report.summary.result);
        UnityEngine.Debug.Log(successMarker + " " + output);
    }
}
