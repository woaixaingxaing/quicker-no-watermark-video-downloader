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

        var helperZip = @"H4sIAFoI3moC/+19a3ccxbXo9/kVTecS9eCZ0Uh+YMYIR9gy+MbYvrZ45Eg6vXpmeqRGPd1Dd48eyDrLQAwytoEEMMGYhEcgPhCwTwLGNjb+L4
lmJH/iL9y9d1X1u2dGwpycu9bVOcE93VW7qnbt2rWfVb+Qig8VpZpdN6zZitT2GsW9+CYny/L/aRu1ed2Ruu991L32TefCtc2/vHrvk9+t3zi3
eedO5/X/7J49V8rl1m/8eeMvFza/u9r54bc/3r6UGylJ3dcv3vvT3+FH99s3N/+y1nn/Svfc5921LyRtUW/qw3Xd0wxT6rx9oXPrnR9vn9/44J
vuG58xsH5b0oGDR6XuxdfWv7/+4+01eH3v8un1W7e6l2/d++L85tWXfrx99p+nX86NlqTOmeudr1/p3Px7581r0jBvHGBu3v1j58//tfnNZ9iR
s293bp+W6stLc27dXrRMW6vrTqlmN6H9zde+6Lx+pfPxl50zn917+wfoS+fm9c2/fNr941s/3v4gJ0lS5/OXO6/d2njjmjTZdizXM0xd6nx9tn
PmiujM+XVo5M23Nv58a+OdK9217zqXr/iDX7/xVefr8901gHa+8+qFje//svH9V2y4OITc5rVXoBL0srXszdkW66U6p5st6GJrWXL0F9q665We
d+Gjo7ttkz3jHOUajt2UVLXR9tqOrqqS0WzZjidplmV7mmfYlpvL8Xc1b7mlu+IXQeDPtv/W0cWTO9eGcfq/bCAFz//VrrYcu6a7fj132X/0jK
YPpO2YplEttTTHjb/joxJvXzRaDUBrLuc5yxXEOYIsuV7dbntQtmZbDWMWhqjoFiPWMZmIVc6HC+uO06ewvlTTW540Qf8AelhbLc0N8MR75jLc
tkxtedExZue8krts1VStZUj+oOF38L0gTcLQob8TjmM7kuZKx5/lb3K5k4cnJ6QxSZ7zvJZbGR5OIUU59/S4enDi5K8njx2Hoor8lP2iYZra8O
5SWVKeNSwo7kpHJ6WRcqm8T4IXe3btk5b27MpLMo0i+JPHWy1Tf1av/trwhnfvfLi0c4+k/PrJyaeOFCTTmNelJ/TavJ1S78AcjFkfHtk1Uirj
/0kntYbmGBwG4G/82fETE+rxE8eeOXxw4sRJ6OeKDHO0bFhyQZLn25rhztltfPaMec+exycDlow262hNer1oeJ7uyIVY06x9R6/XDQ/LLQPa2l
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";
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
