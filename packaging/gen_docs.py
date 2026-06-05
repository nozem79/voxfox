#!/usr/bin/env python3
"""Regenerate the styled HTML manuals from the markdown sources."""
import markdown, base64, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
# The markdown lives at the repo root. gen_docs.py may sit at the root or in
# packaging/, so locate the directory that actually contains README-deb.md.
ROOT = HERE
if not os.path.exists(os.path.join(ROOT, "README-deb.md")):
    parent = os.path.dirname(HERE)
    if os.path.exists(os.path.join(parent, "README-deb.md")):
        ROOT = parent
OUT  = ROOT
logo = os.path.join(ROOT, "voxfox-logo.png")
LOGO = ("data:image/png;base64," + base64.b64encode(open(logo, "rb").read()).decode()
        if os.path.exists(logo) else "")

STYLE = """:root{--accent:#F26A1F;--accent-d:#D9590F;--ink:#23201d;--muted:#756f67;--line:#e7e1d8;--bg:#fbfaf7;--card:#fff;--code-bg:#f4f0ea}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:17px;line-height:1.65;-webkit-font-smoothing:antialiased}.wrap{max-width:820px;margin:0 auto;padding:0 24px 96px}header.hero{display:flex;align-items:center;gap:20px;padding:56px 0 28px;border-bottom:1px solid var(--line);margin-bottom:40px}header.hero img{width:76px;height:76px;flex:none}header.hero h1{font-family:"Fraunces",Georgia,serif;font-weight:600;font-size:46px;line-height:1;margin:0 0 6px}header.hero .badge{display:inline-block;font-size:13px;font-weight:600;color:#fff;background:var(--accent);border-radius:6px;padding:2px 9px;margin-bottom:8px;letter-spacing:.02em}header.hero .tag{color:var(--muted);font-size:16px}header.hero .tag a{color:var(--accent-d)}h2,h3,h4{font-family:"Fraunces",Georgia,serif;font-weight:600;line-height:1.2}h2{font-size:28px;margin:54px 0 14px;padding-top:14px;border-top:2px solid var(--accent);display:inline-block}h3{font-size:21px;margin:30px 0 10px}h4{font-size:18px;margin:22px 0 8px}p{margin:0 0 16px}a{color:var(--accent-d);text-underline-offset:2px;text-decoration-color:rgba(217,89,15,.35)}a:hover{color:var(--accent)}ul,ol{padding-left:24px;margin:0 0 16px}li{margin:4px 0}li::marker{color:var(--accent)}code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.88em;background:var(--code-bg);padding:.12em .4em;border-radius:5px}pre{background:var(--code-bg);border:1px solid var(--line);border-radius:12px;padding:16px 18px;overflow-x:auto;margin:0 0 18px}pre code{background:none;padding:0;font-size:14.5px;line-height:1.55}table{border-collapse:collapse;width:100%;margin:0 0 18px;font-size:15px}th,td{border:1px solid var(--line);padding:8px 12px;text-align:left}th{background:#faf6f0;font-weight:600}td code{white-space:nowrap}blockquote{margin:0 0 18px;padding:6px 18px;border-left:3px solid var(--accent);color:var(--muted);background:#faf6f0;border-radius:0 8px 8px 0}blockquote p{margin:6px 0}hr{border:none;border-top:1px solid var(--line);margin:40px 0}nav.toc{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 22px;margin-bottom:8px}nav.toc .toc-title{font-family:"Fraunces",serif;font-weight:600;font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:8px}nav.toc ul{list-style:none;padding-left:0;margin:0;columns:2;column-gap:28px}nav.toc ul ul{display:none}nav.toc li{margin:3px 0;break-inside:avoid}nav.toc a{text-decoration:none}footer{margin-top:60px;padding-top:20px;border-top:1px solid var(--line);color:var(--muted);font-size:14px}@media (max-width:640px){header.hero{padding-top:36px}header.hero h1{font-size:34px}nav.toc ul{columns:1}}"""
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600'
         '&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">')


def build(md_file, out_file, lang, title, badge, tag, toc_title, footer):
    mdc = markdown.Markdown(extensions=["fenced_code", "tables", "toc", "sane_lists", "attr_list"],
                            extension_configs={"toc": {"permalink": False}})
    body = mdc.convert(open(os.path.join(ROOT, md_file)).read())
    toc  = mdc.toc
    body = re.sub(r"<h1[^>]*>.*?</h1>", "", body, count=1, flags=re.S)
    img  = f'<img src="{LOGO}" alt="VoxFox logo">' if LOGO else ""
    html = (f'<!DOCTYPE html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{title}</title>\n{FONTS}\n<style>{STYLE}</style>\n</head>\n<body>\n'
            f'<div class="wrap">\n<header class="hero">{img}<div>'
            f'<span class="badge">{badge}</span><h1>VoxFox</h1>'
            f'<div class="tag">{tag} · <a href="https://voxfox.nl/manual">voxfox.nl/manual</a></div>'
            f'</div></header>\n<nav class="toc"><div class="toc-title">{toc_title}</div>{toc}</nav>\n'
            f'{body}\n<footer>{footer}</footer>\n</div>\n</body>\n</html>\n')
    open(os.path.join(OUT, out_file), "w").write(html)
    print(out_file, "ok")


if __name__ == "__main__":
    build("README-deb.md", "README-deb.html", "en", "VoxFox (GTK4 / .deb) — Manual",
          "GTK4 · Debian package", "Screen reader &amp; dictation for Linux", "Contents",
          "VoxFox (GTK4 build) · GPLv3 · © 2025 Daniël Vos · <a href='https://voxfox.nl/manual'>voxfox.nl/manual</a>")
    build("README-deb.nl.md", "README-deb.nl.html", "nl", "VoxFox (GTK4 / .deb) — Handleiding",
          "GTK4 · Debian-pakket", "Schermlezer &amp; dicteren voor Linux", "Inhoud",
          "VoxFox (GTK4-versie) · GPLv3 · © 2025 Daniël Vos · <a href='https://voxfox.nl/manual'>voxfox.nl/manual</a>")
