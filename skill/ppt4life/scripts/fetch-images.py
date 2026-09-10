#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch-images.py — 用 BrowserSkill (bsk) 驱动真实浏览器搜索并下载配图，供 PPT 使用。

流程（全部在单个进程内完成，因为 bsk 的 session 不跨 shell 存活）：
  1. 启动会话   bsk session start --no-focus --json
  2. 打开图库    bsk navigate <搜索页> --session <id>
  3. 观察页面    bsk observe --session <id>      （给 agent 参考，可选）
  4. 抽取图片直链 bsk get-html --session <id>    → 正则提取图片 URL
  5. 下载图片    直链 → 本地 assets/img/（走环境代理）
  6. 结束会话    bsk session stop <id>          （finally 保证执行）

依赖：bsk CLI（BrowserSkill）+ 浏览器扩展。安装见 ../references/browser-images.md。
用法示例：
  python fetch-images.py --query "business meeting" --count 6 --out ./assets/img
  python fetch-images.py --query "科研 实验室" --source bing --count 4
  python fetch-images.py --query "product launch" --dry-run
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

IS_WIN = os.name == "nt"

SOURCES = {
    # 免版权图库（最合规，推荐）
    "unsplash": "https://unsplash.com/s/photos/{q}",
    "pexels": "https://www.pexels.com/search/{q}/",
    "pixabay": "https://pixabay.com/images/search/{q}/",
    # 搜索引擎图片（素材更广，注意版权）
    "bing": "https://www.bing.com/images/search?q={q}",
    "baidu": "https://image.baidu.com/search/index?tn=baiduimage&word={q}",
}

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def find_bsk():
    """定位 bsk 可执行文件。"""
    cand = shutil.which("bsk")
    if cand:
        return cand
    home = os.path.expanduser("~")
    for p in (os.path.join(home, ".local", "bin", "bsk.exe" if IS_WIN else "bsk"),
              os.path.join(home, ".local", "bin", "bsk")):
        if os.path.exists(p):
            return p
    return None


def run_bsk(bsk, args, timeout):
    """执行 bsk 命令，输出重定向到临时文件（避免守护进程持有管道导致永久阻塞）。"""
    tmp = tempfile.mkdtemp(prefix="bsk_")
    out_p, err_p = os.path.join(tmp, "out.txt"), os.path.join(tmp, "err.txt")
    try:
        with open(out_p, "w", encoding="utf-8", errors="replace") as of, \
             open(err_p, "w", encoding="utf-8", errors="replace") as ef:
            p = subprocess.Popen([bsk] + args, stdout=of, stderr=ef)
            try:
                rc = p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if IS_WIN:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                                   capture_output=True)
                else:
                    p.kill()
                rc = None
        out = open(out_p, encoding="utf-8", errors="replace").read()
        err = open(err_p, encoding="utf-8", errors="replace").read()
        return rc, out, err
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def extract_image_urls(html):
    """从 HTML 中提取图片 URL。图库/搜索引擎的 CDN 直链优先，其次通用图片后缀。"""
    if not html:
        return []
    patterns = [
        r'https://images\.unsplash\.com/[^\s"\'\\<>)]+',
        r'https://images\.pexels\.com/[^\s"\'\\<>)]+',
        r'https://cdn\.pixabay\.com/[^\s"\'\\<>)]+',
        r'https?://[^\s"\'\\<>)]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\s"\'\\<>)]*)?',
    ]
    found, seen = [], set()
    for pat in patterns:
        for m in re.findall(pat, html, flags=re.I):
            base = m.split("?")[0]
            if base in seen:
                continue
            seen.add(base)
            found.append(m)
    return found


def safe_name(query, idx, url):
    """按 URL 路径扩展名生成安全文件名，默认 .jpg。"""
    path = url.split("?")[0].lower()
    ext = next((e for e in IMG_EXT if path.endswith(e)), ".jpg")
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", query).strip("-")[:30] or "img"
    return f"{slug}-{idx:02d}{ext}"


def download(url, dest, timeout=60):
    """下载图片到本地（优先环境代理，失败再直连）。"""
    proxy = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "").strip()
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    handlers.append(urllib.request.ProxyHandler({}))  # 直连兜底
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ppt4life image fetcher)"})
    with opener.open(req, timeout=timeout) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return os.path.getsize(dest)


def main():
    ap = argparse.ArgumentParser(description="用 BrowserSkill 搜索并下载 PPT 配图")
    ap.add_argument("--query", required=True, help="搜索关键词（英文命中率更高）")
    ap.add_argument("--source", default="unsplash", choices=sorted(SOURCES.keys()),
                    help="图片来源（默认 unsplash 免版权图库）")
    ap.add_argument("--count", type=int, default=6, help="下载数量（默认 6）")
    ap.add_argument("--out", default="./assets/img", help="输出目录（默认 ./assets/img）")
    ap.add_argument("--timeout", type=int, default=120, help="单条 bsk 命令超时秒数")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    args = ap.parse_args()

    url = SOURCES[args.source].format(q=urllib.parse.quote(args.query))
    out_dir = os.path.abspath(args.out)
    plan = {"source": args.source, "query": args.query, "url": url,
            "count": args.count, "out": out_dir}

    if args.dry_run:
        print("[dry-run] 计划：")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    bsk = find_bsk()
    if not bsk:
        print("✗ 未找到 bsk CLI。请先安装 BrowserSkill：", file=sys.stderr)
        print("  Windows: irm https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.ps1 | iex",
              file=sys.stderr)
        print("  详见 ../references/browser-images.md 第 0 节。", file=sys.stderr)
        return 2
    print(f"· bsk: {bsk}")

    rc, out, _ = run_bsk(bsk, ["--version"], 30)
    print(f"· bsk version: {(out or '').strip()}")

    os.makedirs(out_dir, exist_ok=True)
    sid = None
    manifest = []
    try:
        print("· 启动会话…")
        rc, out, err = run_bsk(bsk, ["session", "start", "--no-focus", "--json"], args.timeout)
        try:
            sid = json.loads(out).get("session_id")
        except Exception:
            pass
        if not sid:
            print("✗ 会话启动失败：", (out or err).strip()[:300], file=sys.stderr)
            return 3
        print(f"· session id: {sid}")

        print(f"· 打开：{url}")
        run_bsk(bsk, ["navigate", url, "--session", sid], args.timeout)

        print("· 观察页面（observe）…")
        run_bsk(bsk, ["observe", "--session", sid], args.timeout)

        print("· 抽取图片直链（get-html）…")
        _, html, _ = run_bsk(bsk, ["get-html", "--session", sid], args.timeout)
        urls = extract_image_urls(html)
        print(f"· 找到 {len(urls)} 个图片候选")
        if not urls:
            print("! 未从页面抽取到图片直链。可尝试换 --source，或在浏览器里确认页面已加载。",
                  file=sys.stderr)

        picked = urls[: max(1, args.count)]
        for i, u in enumerate(picked, 1):
            dest = os.path.join(out_dir, safe_name(args.query, i, u))
            try:
                size = download(u, dest)
                manifest.append({"file": os.path.basename(dest), "url": u,
                                 "size": size, "source": args.source})
                print(f"  ✓ {os.path.basename(dest)}  ({size//1024} KB)")
            except Exception as e:
                print(f"  ✗ 下载失败：{u[:80]}  ({e})", file=sys.stderr)

        if manifest:
            mpath = os.path.join(out_dir, "_sources.json")
            with open(mpath, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            print(f"· 已写来源清单：{mpath}（用于在 PPT 标注出处）")
        print(f"· 完成：{len(manifest)} 张图 → {out_dir}")
        return 0
    finally:
        if sid:
            print("· 结束会话…")
            run_bsk(bsk, ["session", "stop", sid], 60)


if __name__ == "__main__":
    sys.exit(main())
