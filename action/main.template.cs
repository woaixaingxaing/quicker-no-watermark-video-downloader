void Main()
{
    try
    {
        var text = qk.Clipboard.GetText() ?? "";
        var url = FirstUrl(text);
        if (string.IsNullOrEmpty(url))
        {
            qk.Ui.Notify("剪贴板里没有找到链接。先复制分享链接，再运行动作。", "warn", "无水印视频下载", 6000);
            return;
        }
        Download(url, text);
    }
    catch (Exception ex)
    {
        qk.Ui.Notify("下载失败：" + ex.Message, "error", "无水印视频下载", 15000);
    }

    string FirstUrl(string text)
    {
        var idx = -1;
        var schemes = new string[] { "https://", "http://" };
        foreach (var scheme in schemes)
        {
            var i = text.IndexOf(scheme, System.StringComparison.OrdinalIgnoreCase);
            if (i >= 0 && (idx < 0 || i < idx)) idx = i;
        }
        if (idx < 0) return null;
        var end = idx;
        while (end < text.Length)
        {
            var ch = text[end];
            if (ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n' || ch == '\u3000') break;
            if (ch > 127) break;
            end++;
        }
        var s = text.Substring(idx, end - idx);
        s = s.TrimEnd('.', ',', ';', ':', '!', '?', ')', ']', '}', '>', '"', '\'');
        return s.Length > 8 ? s : null;
    }

    string FindPython()
    {
        var local = qk.Files.GetKnownFolder("localAppData");
        var list = new string[]
        {
            local + "\\Programs\\Python\\Python312\\python.exe",
            local + "\\Programs\\Python\\Python313\\python.exe",
            local + "\\Programs\\Python\\Python311\\python.exe",
            "C:\\Python312\\python.exe",
            "C:\\Python313\\python.exe"
        };
        foreach (var p in list)
        {
            if (qk.Files.Exists(p)) return p;
        }
        return "python";
    }

    void Download(string url, string clipboardText)
    {
        var dataDir = qk.Files.GetActionDataDirectory();
        qk.Files.CreateDirectory(dataDir);
        var outDir = qk.Files.GetKnownFolder("downloads") + "\\无水印视频";
        qk.Files.CreateDirectory(outDir);

        var helperZip = @"__HELPER_PAYLOAD_PLACEHOLDER__";
        var b64Path = dataDir + "\\helper.b64";
        qk.Files.WriteText(b64Path, helperZip, true);

        var bootstrapPath = dataDir + "\\bootstrap.py";
        var bootstrap = @"import base64, gzip, os, sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
b64_path, py_path = sys.argv[1], sys.argv[2]
src = gzip.decompress(base64.b64decode(open(b64_path, 'r', encoding='ascii').read())).decode('utf-8')
open(py_path, 'w', encoding='utf-8').write(src)
os.execv(sys.executable, [sys.executable, py_path] + sys.argv[3:])
";
        qk.Files.WriteText(bootstrapPath, bootstrap, true);

        var reqPath = dataDir + "\\request.json";
        var resPath = dataDir + "\\result.json";
        var nonce = DateTime.Now.Ticks.ToString();
        var request = "{\"url\":" + Json(url)
            + ",\"clipboard\":" + Json(clipboardText)
            + ",\"outDir\":" + Json(outDir)
            + ",\"dataDir\":" + Json(dataDir)
            + ",\"nonce\":" + Json(nonce) + "}";
        qk.Files.WriteText(reqPath, request, true);
        try
        {
            if (qk.Files.Exists(resPath)) qk.Files.Delete(resPath);
        }
        catch { }

        qk.Ui.Notify("正在解析并下载… 如弹出浏览器，请按提示完成安全验证", "info", "无水印视频下载", 8000);

        var helperPath = dataDir + "\\dyxhs_helper.py";
        var py = FindPython();
        var run = qk.Process.Run(py, new string[] { bootstrapPath, b64Path, helperPath, reqPath, resPath }, dataDir, "utf-8", 0);

        if (!qk.Files.Exists(resPath))
        {
            var detail = (run.StandardError + "\n" + run.StandardOutput).Trim();
            if (detail.Length > 300) detail = detail.Substring(detail.Length - 300);
            qk.Ui.Notify("下载失败：" + (detail.Length == 0 ? "下载助手没有返回结果" : detail), "error", "无水印视频下载", 15000);
            return;
        }

        var resText = qk.Files.ReadText(resPath);
        System.Text.Json.Nodes.JsonNode node;
        try
        {
            node = System.Text.Json.Nodes.JsonNode.Parse(resText);
        }
        catch
        {
            qk.Ui.Notify("下载助手返回了无法识别的结果", "error", "无水印视频下载", 15000);
            return;
        }

        var gotNonce = "";
        try
        {
            if (node["nonce"] != null) gotNonce = (string)node["nonce"];
        }
        catch { }
        if (gotNonce != nonce)
        {
            qk.Ui.Notify("下载结果已过期，请重新运行动作", "error", "无水印视频下载", 12000);
            return;
        }

        var ok = false;
        try
        {
            if (node["ok"] != null) ok = (bool)node["ok"];
        }
        catch { }
        var msg = "";
        try
        {
            if (node["message"] != null) msg = (string)node["message"];
        }
        catch { }

        var files = new System.Collections.Generic.List<string>();
        try
        {
            var arr = node["files"] as System.Text.Json.Nodes.JsonArray;
            if (arr != null)
            {
                foreach (var item in arr)
                {
                    var f = (string)item;
                    if (!string.IsNullOrEmpty(f)) files.Add(f);
                }
            }
        }
        catch { }

        if (ok && files.Count > 0)
        {
            if (string.IsNullOrEmpty(msg)) msg = "下载完成：" + files[0];
            qk.Ui.Notify(msg, "success", "无水印视频下载", 12000);
        }
        else
        {
            if (string.IsNullOrEmpty(msg)) msg = "下载失败";
            qk.Ui.Notify(msg, "error", "无水印视频下载", 15000);
        }
    }

    string Json(string s)
    {
        return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}
