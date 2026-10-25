# -*- coding: utf-8 -*-
"""Quicker 无水印视频下载助手.

两种路径：
1. 抖音：浏览器拦截 aweme/detail 响应，直接下载无水印 CDN 文件（无需人机验证）。
2. 其它平台 / 抖音直连失败：打开 dyxhsdownloader.com，自动填入链接并解析；
   如出现 Turnstile 安全验证，会提示用户在浏览器中完成，再继续下载。

调用：python dyxhs_helper.py request.json result.json
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SITE = "https://dyxhsdownloader.com"
UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/141.0.0.0 Safari/537.36")
AWARE_PROVIDERS = {"douyin", "kuaishou", "tiktok", "instagram", "twitter",
                   "reddit", "youtube", "bilibili", "weibo"}
SUPPORTED_HOST_SUFFIXES = (
    "douyin.com", "iesdouyin.com", "xiaohongshu.com", "xhslink.com",
    "kuaishou.com", "bilibili.com", "b23.tv", "bili2233.cn",
    "weibo.com", "weibo.cn", "t.cn", "tiktok.com", "instagram.com",
    "x.com", "twitter.com", "reddit.com", "redd.it", "youtube.com", "youtu.be",
)

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

_BANNER_ID = "qk-dyxhs-banner"
_log_path = None


def log(msg: str) -> None:
    line = time.strftime("%H:%M:%S") + " " + str(msg)
    print(line, flush=True)
    if _log_path:
        try:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def find_browser() -> str | None:
    for p in CHROME_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return None


def free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def sanitize(name: str, maxlen: int = 80) -> str:
    name = (name or "").strip()
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > maxlen:
        name = name[:maxlen].rstrip(" .")
    return name or "video"


def unique_path(folder: str, base: str, ext: str) -> str:
    path = os.path.join(folder, base + ext)
    i = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({i}){ext}")
        i += 1
    return path


def read_head(path: str, n: int = 4096) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def validate_video(path: str) -> None:
    if not os.path.isfile(path):
        raise RuntimeError("下载文件不存在")
    size = os.path.getsize(path)
    if size < 10_000:
        raise RuntimeError(f"下载的文件过小（{size} 字节），可能解析失败")
    head = read_head(path)
    if b"ftyp" not in head[:2048]:
        raise RuntimeError("下载内容不是有效的 MP4 视频")
    log(f"视频校验通过：{size} 字节")


def validate_zip(path: str) -> None:
    if not os.path.isfile(path) or os.path.getsize(path) < 100:
        raise RuntimeError("图片压缩包生成失败")
    if not zipfile.is_zipfile(path):
        raise RuntimeError("图片压缩包无效")


def http_download(url: str, dest: str, headers: dict, max_bytes: int = 4 << 30) -> int:
    tmp = dest + ".part"
    total = 0
    try:
        with requests.get(url, headers=headers, stream=True, timeout=(30, 180),
                          allow_redirects=True) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if r.status_code >= 400:
                body = b""
                try:
                    body = r.raw.read(400)
                except Exception:
                    pass
                raise RuntimeError(f"下载失败 HTTP {r.status_code}: "
                                   + body.decode("utf-8", "replace")[:180])
            if "application/json" in ctype or "text/html" in ctype:
                body = b""
                try:
                    body = r.raw.read(800)
                except Exception:
                    pass
                raise RuntimeError("下载地址返回错误：" +
                                   body.decode("utf-8", "replace")[:180])
            expected = 0
            try:
                expected = int(r.headers.get("Content-Length") or 0)
            except Exception:
                expected = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if not chunk:
                        continue
                    f.write(chunk)
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError("文件超过 4GB，已停止下载")
            if expected and total != expected:
                raise RuntimeError(f"下载不完整（{total}/{expected} 字节）")
        os.replace(tmp, dest)
        return total
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


def cookies_header(cookies: list, domain_part: str = "") -> str:
    pairs = []
    for c in cookies:
        try:
            if domain_part and domain_part not in (c.get("domain") or ""):
                continue
            pairs.append(f"{c['name']}={c['value']}")
        except Exception:
            pass
    return "; ".join(pairs)


def guess_ext_from_bytes(head: bytes) -> str:
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if head[:4] == b"\x00\x00\x00\x20" and b"ftypavif" in head[:32]:
        return ".avif"
    return ".jpg"


def find_aweme(obj):
    """在 _ROUTER_DATA / __INITIAL_STATE__ 里递归找含 aweme_id 的详情对象."""
    if isinstance(obj, dict):
        if "aweme_id" in obj and ("video" in obj or "images" in obj):
            return obj
        for v in obj.values():
            r = find_aweme(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_aweme(v)
            if r is not None:
                return r
    return None


def douyin_id(url: str) -> str | None:
    m = re.search(r"/video/(\d+)", url) or re.search(r"/share/video/(\d+)", url)
    return m.group(1) if m else None


def is_douyin(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return "douyin.com" in host or "iesdouyin.com" in host


def is_supported(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in SUPPORTED_HOST_SUFFIXES)


URL_TEXT_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.I)
CONTENT_PATTERNS = (
    (("douyin.com", "iesdouyin.com"),
     re.compile(r"^/(?:video|note|share/video|share/note)/\d+", re.I)),
    (("xiaohongshu.com",),
     re.compile(r"^/(?:explore|discovery/item)/[0-9A-Za-z]+", re.I)),
    (("kuaishou.com",),
     re.compile(r"^/(?:short-video|photo|f)/[0-9A-Za-z_-]+", re.I)),
    (("bilibili.com",),
     re.compile(r"^/video/(?:BV[0-9A-Za-z]+|av\d+)", re.I)),
    (("weibo.com",),
     re.compile(r"^/(?:tv/show|status|detail)/[0-9A-Za-z]+", re.I)),
    (("weibo.cn",), re.compile(r"^/(?:status|detail)/\d+", re.I)),
    (("tiktok.com",),
     re.compile(r"^/@[^/]+/(?:video|photo)/\d+", re.I)),
    (("instagram.com",),
     re.compile(r"^/(?:p|reel|tv|share/reel)/[0-9A-Za-z_-]+", re.I)),
    (("x.com", "twitter.com"),
     re.compile(r"^/(?:i/web/)?(?:[^/]+/)?status/\d+", re.I)),
    (("reddit.com",),
     re.compile(r"^/r/[^/]+/comments/[0-9A-Za-z]+", re.I)),
    (("youtube.com",), re.compile(r"^/(?:watch|shorts/|live/)", re.I)),
    (("youtu.be",), re.compile(r"^/[0-9A-Za-z_-]{6,}", re.I)),
)
SHORT_LINK_HOSTS = ("v.douyin.com", "xhslink.com", "b23.tv", "bili2233.cn",
                    "t.cn", "vm.tiktok.com", "vt.tiktok.com", "v.kuaishou.com",
                    "redd.it")
PLATFORM_NAMES = (
    ("douyin.com", "抖音"), ("iesdouyin.com", "抖音"),
    ("xiaohongshu.com", "小红书"), ("xhslink.com", "小红书"),
    ("kuaishou.com", "快手"), ("bilibili.com", "B站"), ("b23.tv", "B站"),
    ("bili2233.cn", "B站"), ("weibo.com", "微博"), ("weibo.cn", "微博"),
    ("t.cn", "微博"), ("tiktok.com", "TikTok"),
    ("instagram.com", "Instagram"), ("x.com", "X"), ("twitter.com", "X"),
    ("reddit.com", "Reddit"), ("redd.it", "Reddit"),
    ("youtube.com", "YouTube"), ("youtu.be", "YouTube"),
)


def platform_name(url: str) -> str:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    for key, name in PLATFORM_NAMES:
        if host == key or host.endswith("." + key):
            return name
    return "该平台"


def extract_urls(text: str) -> list[str]:
    seen: list[str] = []
    for m in URL_TEXT_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,;:!?)]}>'\"")
        if u and u not in seen:
            seen.append(u)
    return seen


def is_content_url(url: str) -> bool:
    if not is_supported(url):
        return False
    try:
        p = urllib.parse.urlparse(url)
        host = (p.hostname or "").lower()
        path = p.path or "/"
        query = urllib.parse.parse_qs(p.query)
    except Exception:
        return False
    for domains, rx in CONTENT_PATTERNS:
        if any(host == d or host.endswith("." + d) for d in domains):
            if rx.search(path):
                return True
            if host in SHORT_LINK_HOSTS and path.strip("/"):
                return True
            if "douyin" in host and query.get("modal_id"):
                return True
            return False
    if host in SHORT_LINK_HOSTS and path.strip("/"):
        return True
    return False


def normalize_url(url: str) -> str:
    try:
        p = urllib.parse.urlparse(url)
        host = (p.hostname or "").lower()
        if "douyin" in host:
            query = urllib.parse.parse_qs(p.query)
            mid = (query.get("modal_id") or [""])[0]
            if mid.isdigit():
                return "https://www.douyin.com/video/" + mid
    except Exception:
        pass
    return url


def pick_url(request: dict) -> str:
    raw = extract_urls(request.get("clipboard") or "")
    given = (request.get("url") or "").strip()
    if given and given not in raw:
        raw.insert(0, given)
    if not raw:
        raise RuntimeError("剪贴板里没有找到链接。先复制作品的分享链接，再运行动作。")
    supported = [u for u in raw if is_supported(u)]
    if not supported:
        raise RuntimeError("暂不支持这个平台，目前支持抖音、小红书、快手、B站、微博、TikTok、Instagram、X/Twitter、Reddit")
    for u in supported:
        if is_content_url(u):
            return normalize_url(u)
    first = supported[0]
    raise RuntimeError(
        f"这是{platform_name(first)}首页/频道链接，不是具体作品。"
        "请在作品页点“分享→复制链接”，或复制带作品 ID 的链接。"
    )


def pick_video_urls(video: dict) -> list[str]:
    urls: list[str] = []
    rates = video.get("bit_rate") or []
    try:
        rates = sorted(rates, key=lambda x: x.get("bit_rate") or 0, reverse=True)
    except Exception:
        pass
    for br in rates:
        pa = br.get("play_addr") or {}
        for u in pa.get("url_list") or []:
            urls.append(u)
    for key in ("play_addr", "play_addr_h264", "play_addr_265"):
        for u in (video.get(key) or {}).get("url_list") or []:
            urls.append(u)
    out, seen = [], set()
    for u in urls:
        if not isinstance(u, str):
            continue
        u = u.replace("http://", "https://")
        if u.startswith("https://") and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def pick_image_url_lists(ad: dict) -> list[list[str]]:
    groups: list[list[str]] = []
    for im in ad.get("images") or []:
        if isinstance(im, str):
            groups.append([im])
            continue
        if not isinstance(im, dict):
            continue
        cand = []
        for key in ("download_url_list", "url_list"):
            for u in im.get(key) or []:
                if isinstance(u, str):
                    cand.append(u)
        if cand:
            groups.append(cand)
    return groups


def download_images(url_groups: list[list[str]], headers: dict, out_dir: str,
                    title: str) -> str:
    tmp_dir = os.path.join(out_dir, ".tmp_" + str(int(time.time() * 1000)))
    os.makedirs(tmp_dir, exist_ok=True)
    saved = 0
    try:
        for idx, urls in enumerate(url_groups, 1):
            last_err = None
            for u in urls[:4]:
                try:
                    tmp = os.path.join(tmp_dir, f"{idx:03d}.part")
                    http_download(u, tmp, headers, max_bytes=128 << 20)
                    ext = guess_ext_from_bytes(read_head(tmp, 32))
                    final = os.path.join(tmp_dir, f"{idx:03d}{ext}")
                    os.replace(tmp, final)
                    saved += 1
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
            if last_err is not None:
                log(f"第 {idx} 张图片下载失败：{last_err}")
        if saved == 0:
            raise RuntimeError("所有图片都下载失败")
        zip_path = unique_path(out_dir, sanitize(title), ".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(os.listdir(tmp_dir)):
                if name.endswith(".part"):
                    continue
                z.write(os.path.join(tmp_dir, name), arcname=name)
        validate_zip(zip_path)
        return zip_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def douyin_direct(url: str, out_dir: str, data_dir: str) -> dict:
    browser_path = find_browser()
    if not browser_path:
        raise RuntimeError("未找到 Chrome/Edge 浏览器")
    vid = douyin_id(url)
    targets = [url]
    if vid and f"/video/{vid}" not in url:
        targets.append(f"https://www.douyin.com/video/{vid}")

    profile = os.path.join(data_dir, "douyin-profile")
    os.makedirs(profile, exist_ok=True)
    holder: dict = {}
    cookies: list = []
    ad = None

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=profile,
            executable_path=browser_path,
            headless=True,
            accept_downloads=False,
            user_agent=UA_DESKTOP,
            locale="zh-CN",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled",
                  "--no-first-run", "--no-default-browser-check"],
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            def on_response(r):
                if "aweme/detail" not in r.url or r.request.method != "GET":
                    return
                try:
                    body = r.text()
                    data = json.loads(body)
                    item = data.get("aweme_detail")
                    if item and ("video" in item or "images" in item):
                        holder["ad"] = item
                        log("已截获抖音详情数据")
                except Exception:
                    pass

            page.on("response", on_response)
            for t in targets:
                try:
                    page.goto(t, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    log(f"打开抖音页面失败：{e}")
                deadline = time.time() + 35
                while time.time() < deadline and "ad" not in holder:
                    page.wait_for_timeout(500)
                if "ad" in holder:
                    break
            if "ad" not in holder:
                for expr in ("window._ROUTER_DATA", "window.__INITIAL_STATE__"):
                    try:
                        obj = page.evaluate(f"() => {expr} || null")
                        found = find_aweme(obj)
                        if found:
                            holder["ad"] = found
                            log("已从页面状态中找到抖音数据")
                            break
                    except Exception:
                        pass
            try:
                cookies = ctx.cookies()
            except Exception:
                cookies = []
            ad = holder.get("ad")
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    if not ad:
        raise RuntimeError("未能获取抖音作品信息（可能需要登录或验证）")

    title = ad.get("desc") or ad.get("item_title") or f"douyin_{ad.get('aweme_id', '')}"
    author = ((ad.get("author") or {}).get("nickname") or "").strip()
    base = sanitize((author + " - " + title) if author else title, 90)

    video = ad.get("video") or {}
    vurls = pick_video_urls(video)
    headers = {
        "User-Agent": UA_DESKTOP,
        "Referer": "https://www.douyin.com/",
        "Accept": "*/*",
    }
    ck = cookies_header(cookies, "douyin.com")
    if ck:
        headers["Cookie"] = ck

    last_err = None
    if vurls and not ad.get("images"):
        dest = unique_path(out_dir, base, ".mp4")
        for u in vurls:
            try:
                http_download(u, dest, headers)
                validate_video(dest)
                return {
                    "ok": True, "provider": "douyin", "kind": "video",
                    "title": title, "files": [dest],
                    "message": "已保存无水印视频：" + os.path.basename(dest),
                }
            except Exception as e:
                last_err = e
                log(f"抖音视频源下载失败，尝试下一个：{e}")
        raise RuntimeError(f"抖音视频下载失败：{last_err}")

    groups = pick_image_url_lists(ad)
    if groups:
        zip_path = download_images(groups, headers, out_dir, title)
        return {
            "ok": True, "provider": "douyin", "kind": "images_zip",
            "title": title, "files": [zip_path],
            "message": f"已保存 {len(groups)} 张图片：" + os.path.basename(zip_path),
        }
    raise RuntimeError("该抖音作品没有可下载的视频或图片")


def inject_banner(page, text: str) -> None:
    try:
        page.evaluate(
            """(args) => {
                let d = document.getElementById(args.id);
                if (!d) {
                    d = document.createElement('div');
                    d.id = args.id;
                    d.style.cssText = 'position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:2147483647;background:rgba(16,16,16,.94);color:#fff;padding:10px 16px;border-radius:10px;font:13px/1.6 "Microsoft YaHei",sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.45);pointer-events:none;max-width:82vw;text-align:center;border:1px solid rgba(255,255,255,.15);';
                    document.body.appendChild(d);
                }
                d.textContent = args.text;
            }""",
            {"id": _BANNER_ID, "text": text},
        )
    except Exception:
        pass


def focus_browser_window(pid: int, flash: bool = False) -> None:
    try:
        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def cb(hwnd, _):
            wpid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        user32.EnumWindows(cb, 0)
        if found:
            hwnd = found[0]
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            if flash:
                class FLASHWINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_ulong),
                                ("hwnd", ctypes.c_void_p),
                                ("dwFlags", ctypes.c_ulong),
                                ("uCount", ctypes.c_ulong),
                                ("dwTimeout", ctypes.c_ulong)]
                fi = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 3 | 12, 6, 0)
                user32.FlashWindowEx(ctypes.byref(fi))
    except Exception:
        pass


def launch_cdp_chrome(profile: str, port: int):
    browser_path = find_browser()
    if not browser_path:
        raise RuntimeError("未找到 Chrome/Edge 浏览器")
    args = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-features=Translate",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--window-size=1280,1000", "--window-position=80,40",
        "about:blank",
    ]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                json.load(r)
            return proc
        except Exception:
            if proc.poll() is not None:
                break
            time.sleep(0.4)
    try:
        proc.terminate()
    except Exception:
        pass
    raise RuntimeError("浏览器调试端口未能启动")


def site_download(url: str, out_dir: str, data_dir: str) -> dict:
    os.makedirs(data_dir, exist_ok=True)
    port = free_port()
    profile = os.path.join(data_dir, "site-profile")
    os.makedirs(profile, exist_ok=True)
    try:
        proc = launch_cdp_chrome(profile, port)
    except Exception as e:
        log(f"浏览器资料目录被占用，改用临时目录：{e}")
        port = free_port()
        profile = os.path.join(data_dir, "site-profile-" + str(int(time.time())))
        os.makedirs(profile, exist_ok=True)
        proc = launch_cdp_chrome(profile, port)
    focus_browser_window(proc.pid)

    parsed: dict = {}
    browser = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(30000)
            try:
                page.bring_to_front()
            except Exception:
                pass

            def on_response(r):
                if "/api/parse" not in r.url or r.request.method != "POST":
                    return
                try:
                    parsed["status"] = r.status
                    parsed["ctype"] = r.headers.get("content-type") or ""
                    parsed["body"] = r.text()
                    log(f"/api/parse 响应：HTTP {r.status}")
                except Exception as e:
                    parsed["read_error"] = str(e)

            page.on("response", on_response)

            try:
                page.goto(SITE + "/", wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                log(f"打开站点失败：{e}")
            try:
                page.bring_to_front()
                focus_browser_window(proc.pid, flash=True)
            except Exception:
                pass

            # 等待页面主输入框（Cloudflare 的独立验证页需要用户先点一下）
            deadline = time.time() + 180
            input_ready = False
            while time.time() < deadline:
                try:
                    loc = page.locator('input[type=text]').first
                    if loc.count() and loc.is_visible():
                        input_ready = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            if not input_ready:
                raise RuntimeError("站点页面未加载完成，可能安全验证未完成或网络异常")

            inject_banner(page, "Quicker 正在自动解析… 如出现“安全验证”，请在下方点击验证，完成后会自动继续。")
            try:
                page.locator('input[type=text]').first.fill(url)
            except Exception:
                raise RuntimeError("无法自动填入链接")
            try:
                page.wait_for_function(
                    "() => { const b=document.querySelector('button[type=submit]'); return b && !b.disabled; }",
                    timeout=15000,
                )
            except Exception:
                pass
            try:
                page.bring_to_front()
                focus_browser_window(proc.pid, flash=True)
            except Exception:
                pass

            def click_parse():
                try:
                    page.locator('button[type=submit]').first.click(timeout=10000)
                    log("已点击解析")
                    return True
                except Exception as e:
                    log(f"点击解析失败：{e}")
                    return False

            click_parse()
            parse_deadline = time.time() + 480
            retries = 0
            last_err_text = ""
            last_retry = 0.0
            last_iframe_scroll = 0.0
            focused_for_verify = False

            while time.time() < parse_deadline and "body" not in parsed:
                try:
                    state = page.evaluate(
                        """(bid) => {
                            const b = document.querySelector('button[type=submit]');
                            const errs = [...document.querySelectorAll('.input-error-msg')].map(e=>e.innerText.trim()).filter(Boolean);
                            const slot = document.querySelector('.turnstile-slot');
                            const ifr = slot ? slot.querySelector('iframe')
                                : document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]');
                            let rect = null;
                            if (ifr) { const r = ifr.getBoundingClientRect(); rect = {w:r.width,h:r.height,top:r.top}; }
                            return {
                                btn: b ? b.innerText.trim() : '',
                                disabled: b ? b.disabled : true,
                                err: errs.join(' | '),
                                iframe: !!ifr,
                                rect,
                                hasResult: document.body.innerText.includes('下载无水印视频') || document.body.innerText.includes('下载全部')
                            };
                        }""",
                        _BANNER_ID,
                    )
                except Exception:
                    state = {}

                if state.get("iframe") and (not last_iframe_scroll or time.time() - last_iframe_scroll > 15):
                    try:
                        page.locator(".turnstile-slot").first.scroll_into_view_if_needed(timeout=3000)
                        last_iframe_scroll = time.time()
                        inject_banner(page, "检测到安全验证，请点击页面下方 Cloudflare 验证框，完成后会自动继续。")
                        if not focused_for_verify:
                            focused_for_verify = True
                            log("检测到安全验证，等待用户点击")
                            try:
                                page.bring_to_front()
                            except Exception:
                                pass
                            focus_browser_window(proc.pid, flash=True)
                            try:
                                shot = os.path.join(data_dir, "logs", "verify_prompt.png")
                                os.makedirs(os.path.dirname(shot), exist_ok=True)
                                page.screenshot(path=shot, full_page=False)
                            except Exception:
                                pass
                    except Exception:
                        pass

                err_text = state.get("err") or ""
                now = time.time()
                if err_text:
                    if err_text != last_err_text:
                        last_err_text = err_text
                        log("站点提示：" + err_text)
                    if ("验证" in err_text or "verify" in err_text.lower()) and retries < 6 and now - last_retry > 25:
                        retries += 1
                        last_retry = now
                        focused_for_verify = False
                        last_iframe_scroll = 0.0
                        inject_banner(page, f"安全验证未完成，正在重新发起（{retries}/6），请点击浏览器里的验证框。")
                        try:
                            page.bring_to_front()
                            focus_browser_window(proc.pid, flash=True)
                        except Exception:
                            pass
                        time.sleep(1.5)
                        try:
                            page.locator('input[type=text]').first.fill(url)
                        except Exception:
                            pass
                        click_parse()
                    elif "未找到" in err_text or "不支持" in err_text or "无效" in err_text:
                        raise RuntimeError(err_text)
                    elif "频繁" in err_text or "稍后" in err_text or "429" in err_text:
                        raise RuntimeError(err_text)
                time.sleep(1.2)

            if "body" not in parsed:
                try:
                    shot = os.path.join(data_dir, "logs", "parse_timeout.png")
                    os.makedirs(os.path.dirname(shot), exist_ok=True)
                    page.screenshot(path=shot, full_page=True)
                    open(os.path.join(data_dir, "logs", "parse_timeout.html"), "w", encoding="utf-8").write(page.content())
                    log("超时截图：" + shot)
                except Exception:
                    pass
                raise RuntimeError("等待解析超时：如果你看到了安全验证，请重新运行动作并完成验证")

            ctype = (parsed.get("ctype") or "").lower()
            if "application/json" not in ctype:
                raise RuntimeError("解析接口返回异常（HTTP %s），通常是安全验证未通过" % parsed.get("status"))
            try:
                payload = json.loads(parsed.get("body") or "{}")
            except Exception:
                raise RuntimeError("解析结果不是有效 JSON")
            if "error" in payload:
                raise RuntimeError(str(payload.get("error")))
            data = payload.get("data") or {}
            provider = payload.get("provider") or "unknown"
            resolved = payload.get("resolvedUrl") or url
            inject_banner(page, "解析成功，正在下载…")
            log(f"解析成功：provider={provider} type={data.get('type')}")

            title = sanitize(data.get("title") or "video", 90)
            if data.get("images"):
                files = download_site_images(data, provider, resolved, out_dir, title, page)
                return {
                    "ok": True, "provider": provider, "kind": "images_zip",
                    "title": title, "files": files,
                    "message": f"已保存 {len(data.get('images') or [])} 张图片：" + os.path.basename(files[0]),
                }

            video_url = data.get("videoUrl") or ""
            if not video_url:
                raise RuntimeError("解析结果中没有视频地址")
            dest = unique_path(out_dir, title, ".mp4")
            ua = UA_DESKTOP
            try:
                ua = page.evaluate("navigator.userAgent") or UA_DESKTOP
            except Exception:
                pass
            cookies = []
            try:
                cookies = ctx.cookies()
            except Exception:
                cookies = []
            headers = {
                "User-Agent": ua,
                "Referer": SITE + "/",
                "Accept": "*/*",
            }
            ck = cookies_header(cookies, "dyxhsdownloader.com")
            if ck:
                headers["Cookie"] = ck

            audio = data.get("audioUrl")
            if audio:
                inject_banner(page, "正在合并音视频，请保持浏览器窗口打开…")
                log("该视频需要浏览器内合并音视频，点击主下载按钮")
                try:
                    with page.expect_download(timeout=600000) as di:
                        page.locator(".dl-btn.primary").first.click(timeout=20000)
                    dl = di.value
                    dl.save_as(dest)
                    validate_video(dest)
                    return {
                        "ok": True, "provider": provider, "kind": "video",
                        "title": title, "files": [dest],
                        "message": "已保存无水印视频：" + os.path.basename(dest),
                    }
                except PWTimeout:
                    log("浏览器下载事件超时，尝试直接下载视频流")
                except Exception as e:
                    log(f"浏览器下载失败：{e}")

            errs = []
            candidates = []
            if provider in AWARE_PROVIDERS:
                q = {"source": resolved, "kind": "video",
                     "filename": title + ".mp4", "download": "1"}
                candidates.append(SITE + "/api/download?" + urllib.parse.urlencode(q))
                q2 = dict(q)
                q2["alt"] = "1"
                candidates.append(SITE + "/api/download?" + urllib.parse.urlencode(q2))
            qp = {"url": video_url, "filename": title + ".mp4", "download": "1"}
            if data.get("proxyCookie"):
                qp["cookie"] = data["proxyCookie"]
            candidates.append(SITE + "/api/proxy?" + urllib.parse.urlencode(qp))

            for u in candidates:
                try:
                    log("尝试下载：" + u.split("?")[0])
                    http_download(u, dest, headers)
                    validate_video(dest)
                    return {
                        "ok": True, "provider": provider, "kind": "video",
                        "title": title, "files": [dest],
                        "message": "已保存无水印视频：" + os.path.basename(dest),
                    }
                except Exception as e:
                    errs.append(str(e))
                    log(f"下载失败：{e}")
            raise RuntimeError("视频下载失败：" + "；".join(errs[-2:]))
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def download_site_images(data: dict, provider: str, resolved: str,
                         out_dir: str, title: str, page) -> list[str]:
    images = data.get("images") or []
    if not isinstance(images, list) or not images:
        raise RuntimeError("解析结果中没有图片")
    tmp_dir = os.path.join(out_dir, ".tmp_img_" + str(int(time.time() * 1000)))
    os.makedirs(tmp_dir, exist_ok=True)
    ua = UA_DESKTOP
    try:
        ua = page.evaluate("navigator.userAgent") or UA_DESKTOP
    except Exception:
        pass
    headers = {"User-Agent": ua, "Referer": SITE + "/", "Accept": "*/*"}
    saved = 0
    try:
        for idx, item in enumerate(images):
            url = item if isinstance(item, str) else (item or {}).get("url", "")
            if not url:
                continue
            if provider in AWARE_PROVIDERS:
                q = {"source": resolved, "kind": "image", "index": str(idx),
                     "download": "1"}
                candidates = [SITE + "/api/download?" + urllib.parse.urlencode(q)]
            else:
                q = {"url": url, "download": "1"}
                if data.get("proxyCookie"):
                    q["cookie"] = data["proxyCookie"]
                candidates = [SITE + "/api/proxy?" + urllib.parse.urlencode(q)]
            ok = False
            last = None
            for cu in candidates:
                try:
                    tmp = os.path.join(tmp_dir, f"{idx+1:03d}.part")
                    http_download(cu, tmp, headers, max_bytes=128 << 20)
                    ext = guess_ext_from_bytes(read_head(tmp, 32))
                    os.replace(tmp, os.path.join(tmp_dir, f"{idx+1:03d}{ext}"))
                    saved += 1
                    ok = True
                    break
                except Exception as e:
                    last = e
            if not ok:
                log(f"第 {idx+1} 张图片下载失败：{last}")
        if saved == 0:
            raise RuntimeError("所有图片都下载失败")
        zip_path = unique_path(out_dir, title, ".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(os.listdir(tmp_dir)):
                if not name.endswith(".part"):
                    z.write(os.path.join(tmp_dir, name), arcname=name)
        validate_zip(zip_path)
        return [zip_path]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run(request: dict) -> dict:
    out_dir = request.get("outDir") or os.path.join(os.path.expanduser("~"), "Downloads", "无水印视频")
    data_dir = request.get("dataDir") or os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)
    url = pick_url(request)
    log("解析使用链接：" + url[:200])

    direct_error = None
    if is_douyin(url):
        try:
            return douyin_direct(url, out_dir, data_dir)
        except Exception as e:
            direct_error = str(e)
            log(f"抖音直连失败，改用站点兜底：{direct_error}")

    try:
        return site_download(url, out_dir, data_dir)
    except Exception as e:
        if direct_error:
            raise RuntimeError(f"抖音直连失败（{direct_error}）；站点兜底也失败（{e}）")
        raise


def main() -> int:
    global _log_path
    if len(sys.argv) < 3:
        print("usage: dyxhs_helper.py request.json result.json", file=sys.stderr)
        return 2
    req_path, res_path = sys.argv[1], sys.argv[2]
    nonce = ""
    result_path = res_path
    try:
        with open(req_path, "r", encoding="utf-8-sig") as f:
            request = json.load(f)
        nonce = request.get("nonce") or ""
        data_dir = request.get("dataDir") or os.path.dirname(os.path.abspath(__file__))
        _log_path = os.path.join(data_dir, "run.log")
        try:
            open(_log_path, "w", encoding="utf-8").close()
        except Exception:
            _log_path = None
        log("收到链接：" + (request.get("url") or "")[:200])
        result = run(request)
    except Exception as e:
        result = {"ok": False, "error": str(e), "message": str(e)}
        log("失败：" + str(e))
    result["nonce"] = nonce
    try:
        tmp = result_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        os.replace(tmp, result_path)
    except Exception as e:
        print("写结果失败：" + str(e), file=sys.stderr)
        return 3
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
