# 无水印视频下载 · Quicker 动作

复制一条分享链接，然后运行 Quicker 动作，视频会自动下载。抖音链接会直接取得无水印作品地址；小红书等其他平台会自动打开解析页面，出现 Cloudflare 安全验证时由你手动点一下，验证完成后继续下载。

支持：抖音、小红书、快手、Bilibili、微博、TikTok、Instagram、X/Twitter、Reddit、YouTube。视频默认保存到：

```text
C:\Users\<你的用户名>\Downloads\无水印视频
```

## 工作方式

动作由两层组成：

- `action/main.cs` 是 Quicker 里实际运行的 C# 脚本。它读取剪贴板，在首次运行时把内置的 Python 助手释放到当前动作的数据目录。
- `helper/dyxhs_helper.py` 负责链接识别、抖音直连解析，以及其他平台的浏览器解析和文件下载。

抖音路径会启动一个本地浏览器会话，从作品详情接口中寻找无水印源并直接下载；它不依赖第三方解析站点。其他平台会打开正常可见的 Chrome/Edge 窗口，由 dyxhsdownloader.com 完成解析。安全验证只会被展示给用户，动作不会自动点击或绕过验证码。

整段分享文案通常也能直接使用。动作会在剪贴板文本中优先挑选具体作品链接；若只复制到抖音/小红书首页，会立即给出明确提示，不会让浏览器空转等待。

## 环境要求

- Windows
- 已安装的桌面 Chrome 或 Edge
- Python 3.10 或更高版本（当前在 Python 3.12 验证）
- Python 依赖：`requests`、`playwright`

安装依赖：

```powershell
python -m pip install -U requests playwright
```

脚本使用本机 Chrome/Edge，不需要额外下载 Playwright 自带的浏览器内核。

动作默认按以下顺序寻找 Python：

```text
%LOCALAPPDATA%\Programs\Python\Python312\python.exe
%LOCALAPPDATA%\Programs\Python\Python313\python.exe
%LOCALAPPDATA%\Programs\Python\Python311\python.exe
C:\Python312\python.exe
C:\Python313\python.exe
python
```

如果你的 Python 安装在其他位置，修改 `action/main.cs` 或 `action/main.template.cs` 里的 `FindPython()`。

## 在 Quicker 中安装

1. 在 Quicker 中创建一个新的 C# 脚本动作。
2. 将 `action/main.cs` 的完整内容粘贴到脚本编辑器。
3. 将动作超时时间设置为至少 `1500000` 毫秒（25 分钟）。仓库里的 `action/operation.json` 是对应的运行配置。
4. 首次运行会写入动作数据目录并弹出相应权限，允许剪贴板读取、文件写入和启动 Python/浏览器进程。
5. 推荐动作名称：`无水印视频下载`。图标与说明见 `action/info.yaml`。

## 使用

1. 在抖音、小红书等平台打开具体作品。
2. 点击“分享 → 复制链接”，或直接复制包含 `/video/`、`/note/`、`/explore/`、`/short-video/`、`/status/` 等作品 ID 的链接。
3. 运行 Quicker 动作。
4. 如果动作打开了浏览器并在页面下方显示“安全验证”，手动完成验证；程序会自动继续解析和下载。

完成后会弹出保存位置。重复下载同一作品时，新文件会以 ` (2)`、` (3)` 等后缀保存，不会覆盖旧文件。

## 本地数据

动作只在当前电脑工作。以下内容会写入当前 Quicker 动作的数据目录：

- `bootstrap.py`、`helper.b64`、`dyxhs_helper.py`：首次运行时释放的 Python 助手。
- `request.json`、`result.json`、`run.log`：本次调用状态与进度。
- `douyin-profile/`、`site-profile/`：浏览器会话目录。
- `logs/`：验证页面截图与超时诊断。

视频和图片本身保存到系统的“下载”目录，不进入 Quicker 动作数据目录。项目中没有账号口令、Cookie 或令牌。

## 常见问题

### 提示“这是抖音/小红书首页链接”

剪贴板里没有作品链接。请重新打开具体作品后复制分享链接，或复制浏览器地址栏中带作品 ID 的地址。

### 浏览器窗口没有出现在前面

动作会尝试把 Chrome/Edge 窗口置顶并闪烁。如果被其他窗口遮挡，请手动切换到浏览器，完成 Cloudflare 验证。下一次运行仍会自动继续。

### 站点解析服务暂时不可用

其他平台依赖 dyxhsdownloader.com 的解析结果。若提示 500 或“解析服务暂时不可用”，通常是上游服务异常；稍后重试，或把链接切换成平台官方分享链接。

### 下载文件过小或不是 MP4

这通常表示解析返回的是封面、占位内容或过期地址。重新复制一次官方分享链接后再运行。可先查看动作数据目录中的 `run.log`。

## 源码结构

```text
action/
  main.cs                 可直接粘贴到 Quicker 的最终脚本
  main.template.cs        未嵌入助手 payload 的模板
  info.yaml               动作标题、说明与图标
  operation.json          QkEval 运行配置（25 分钟超时）
helper/
  dyxhs_helper.py         下载助手源码
tools/
  build_payload.py        从助手源码重新生成 main.cs
```

修改 Python 助手后，在仓库根目录执行：

```powershell
python tools/build_payload.py
```

然后把更新后的 `action/main.cs` 粘贴回 Quicker 动作。

## 合规提示

本仓库仅用于个人备份、素材整理和技术研究。请遵守各平台服务条款、版权要求和当地法律；不要下载或传播未经授权的内容。
