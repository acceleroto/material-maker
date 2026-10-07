// Installed by `mmx to-unity --verify` into Assets/Editor/MaterialMakerAgent/ (Editor-only, never in builds).
// Run: Unity -batchmode -quit -projectPath <p> -logFile <log> -executeMethod MMAgentVerify.Run
//            -mmFolder Assets/Materials/Generated/<Name> -mmReport <abs report.json>
// Imports the folder, then checks every material in it: shader found + compiled + matching the active
// render pipeline, every texture reference in the .mat resolves to an imported texture, importer settings
// (normal maps as NormalMap, data maps linear). Writes a JSON report; exit 0 ok / 1 problems / 2 bad args / 3 exception.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

public static class MMAgentVerify
{
    [Serializable]
    public class TextureRef
    {
        public string property;
        public string guid;
        public string path;
        public bool resolved;
        public bool assigned;
        public string importer_type;
        public bool srgb;
        public int width;
        public int height;
    }

    [Serializable]
    public class MaterialReport
    {
        public string path;
        public string name;
        public string guid;
        public string shader;
        public bool shader_found;
        public bool shader_has_errors;
        public bool shader_supported;
        public List<TextureRef> textures = new List<TextureRef>();
        public List<string> errors = new List<string>();
        public List<string> warnings = new List<string>();
    }

    [Serializable]
    public class Report
    {
        public int mm_unity_verify = 1;
        public bool ok;
        public string unity_version;
        public string folder;
        public string render_pipeline;
        public string render_pipeline_asset;
        public List<string> assets = new List<string>();
        public List<MaterialReport> materials = new List<MaterialReport>();
        public List<string> errors = new List<string>();
        public List<string> warnings = new List<string>();
    }

    static readonly Regex TexRef = new Regex(@"^\s*-\s*(\w+):\s*$|m_Texture:\s*\{fileID:\s*(\d+),\s*guid:\s*([0-9a-f]{32})");

    static string Arg(string name)
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
            if (args[i] == name)
                return args[i + 1];
        return null;
    }

    public static void Run()
    {
        string folder = Arg("-mmFolder");
        string reportPath = Arg("-mmReport");
        var report = new Report { unity_version = Application.unityVersion, folder = folder };
        int code = 0;
        try
        {
            if (string.IsNullOrEmpty(folder) || string.IsNullOrEmpty(reportPath))
            {
                report.errors.Add("usage: -mmFolder Assets/... -mmReport <abs path>");
                code = 2;
            }
            else
            {
                code = Verify(folder, report);
            }
        }
        catch (Exception e)
        {
            report.errors.Add("exception: " + e);
            code = 3;
        }
        report.ok = code == 0;
        string json = JsonUtility.ToJson(report, true);
        if (!string.IsNullOrEmpty(reportPath))
            File.WriteAllText(reportPath, json);
        Debug.Log("MMAgentVerify: " + (report.ok ? "OK" : "FAILED") + " (exit " + code + ")\n" + json);
        EditorApplication.Exit(code);
    }

    static int Verify(string folder, Report report)
    {
        folder = folder.TrimEnd('/');
        if (!AssetDatabase.IsValidFolder(folder))
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
        if (!AssetDatabase.IsValidFolder(folder))
        {
            report.errors.Add("folder not found in the AssetDatabase: " + folder);
            return 1;
        }
        AssetDatabase.ImportAsset(folder, ImportAssetOptions.ImportRecursive | ImportAssetOptions.ForceUpdate
                                          | ImportAssetOptions.ForceSynchronousImport);

        RenderPipelineAsset rp = GraphicsSettings.currentRenderPipeline;
        report.render_pipeline = rp == null ? "Built-in" : rp.GetType().FullName;
        report.render_pipeline_asset = rp == null ? "" : AssetDatabase.GetAssetPath(rp);

        foreach (string guid in AssetDatabase.FindAssets("", new[] { folder }))
            report.assets.Add(AssetDatabase.GUIDToAssetPath(guid));

        string[] matGuids = AssetDatabase.FindAssets("t:Material", new[] { folder });
        if (matGuids.Length == 0)
            report.errors.Add("no material in " + folder);
        foreach (string guid in matGuids)
            report.materials.Add(CheckMaterial(AssetDatabase.GUIDToAssetPath(guid), guid, rp));

        bool failed = report.errors.Count > 0;
        foreach (MaterialReport m in report.materials)
        {
            failed |= m.errors.Count > 0;
            foreach (string w in m.warnings)
                report.warnings.Add(m.name + ": " + w);
        }
        return failed ? 1 : 0;
    }

    static MaterialReport CheckMaterial(string path, string guid, RenderPipelineAsset rp)
    {
        var r = new MaterialReport { path = path, guid = guid };
        var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (mat == null)
        {
            r.errors.Add("material did not load");
            return r;
        }
        r.name = mat.name;
        Shader shader = mat.shader;
        r.shader = shader == null ? "" : shader.name;
        r.shader_found = shader != null && shader.name != "Hidden/InternalErrorShader";
        if (!r.shader_found)
            r.errors.Add("shader missing (material falls back to the error shader; magenta)");
        else
        {
            r.shader_has_errors = ShaderUtil.ShaderHasError(shader);
            r.shader_supported = shader.isSupported;
            if (r.shader_has_errors)
                r.errors.Add("shader has compile errors: " + shader.name);
            if (!r.shader_supported)
                r.errors.Add("shader not supported on this platform/pipeline: " + shader.name);
            string pipe = rp == null ? "Built-in" : rp.GetType().Name;
            bool urpShader = shader.name.StartsWith("Universal Render Pipeline/");
            bool hdrpShader = shader.name.StartsWith("HDRP/");
            if (urpShader && !pipe.Contains("Universal"))
                r.errors.Add("URP shader but the active pipeline is " + pipe);
            if (hdrpShader && !pipe.Contains("HD"))
                r.errors.Add("HDRP shader but the active pipeline is " + pipe);
            if (!urpShader && !hdrpShader && rp != null)
                r.errors.Add("Built-in shader " + shader.name + " but the active pipeline is " + pipe + " (renders magenta)");
        }

        // Texture references as written in the .mat file (a broken GUID shows up here, not via GetTexture).
        string currentProp = null;
        foreach (string line in File.ReadAllLines(path))
        {
            Match m = TexRef.Match(line);
            if (!m.Success)
                continue;
            if (m.Groups[1].Success)
            {
                currentProp = m.Groups[1].Value;
                continue;
            }
            string texGuid = m.Groups[3].Value;
            if (m.Groups[2].Value == "0" || texGuid == "00000000000000000000000000000000")
                continue;
            var t = new TextureRef { property = currentProp, guid = texGuid };
            t.path = AssetDatabase.GUIDToAssetPath(texGuid);
            var tex = string.IsNullOrEmpty(t.path) ? null : AssetDatabase.LoadAssetAtPath<Texture>(t.path);
            t.resolved = tex != null;
            t.assigned = currentProp != null && mat.HasProperty(currentProp) && mat.GetTexture(currentProp) == tex && tex != null;
            if (tex != null)
            {
                t.width = tex.width;
                t.height = tex.height;
            }
            if (!t.resolved)
                r.errors.Add(currentProp + ": texture guid " + texGuid + " does not resolve" +
                             (string.IsNullOrEmpty(t.path) ? "" : " (" + t.path + ")"));
            else if (!t.assigned)
                r.warnings.Add(currentProp + ": not a property of " + r.shader + " (ignored by the shader)");
            var imp = string.IsNullOrEmpty(t.path) ? null : AssetImporter.GetAtPath(t.path) as TextureImporter;
            if (imp != null)
            {
                t.importer_type = imp.textureType.ToString();
                t.srgb = imp.sRGBTexture;
                string file = Path.GetFileNameWithoutExtension(t.path);
                if (file.EndsWith("_normal") && imp.textureType != TextureImporterType.NormalMap)
                    r.errors.Add(t.path + " is a normal map but imported as " + imp.textureType);
                bool colour = file.EndsWith("_albedo") || file.EndsWith("_emission");
                if (!colour && imp.textureType == TextureImporterType.Default && imp.sRGBTexture)
                    r.warnings.Add(t.path + " is a data map but imported as sRGB");
            }
            r.textures.Add(t);
        }
        if (r.textures.Count == 0)
            r.warnings.Add("material references no textures");
        return r;
    }
}
