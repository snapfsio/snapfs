#!/usr/bin/env python3
#
# Copyright (c) 2026 SnapFS, LLC
#

"""Build a small GitHub Pages site from repository markdown docs."""

import argparse
import re
import shutil
from pathlib import Path

LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)")


def rewrite_links(content: str, page_kind: str) -> str:
    """Rewrite markdown links for pretty-url HTML output."""

    def replace(match: re.Match) -> str:
        label = match.group("label")
        target = match.group("target")

        if "://" in target or target.startswith("#") or target.startswith("mailto:"):
            return match.group(0)

        if target.startswith("/mnt/") or target.startswith("file://"):
            return label

        if not target.endswith(".md"):
            return match.group(0)

        if page_kind == "root":
            if target == "README.md" or target == "docs/README.md":
                rewritten = "./"
            elif target.startswith("docs/"):
                rewritten = target[:-3] + "/"
            else:
                rewritten = "docs/" + target[:-3] + "/"
        else:
            if target == "README.md" or target == "docs/README.md":
                rewritten = "../"
            elif target.startswith("docs/"):
                rewritten = "../" + target[len("docs/") : -3] + "/"
            else:
                rewritten = target[:-3] + "/"

        return f"[{label}]({rewritten})"

    return LINK_RE.sub(replace, content)


def extract_title(content: str, fallback: str) -> str:
    """Extract the first markdown h1 title or use the fallback."""
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def wrap_markdown(content: str, title: str) -> str:
    """Add Jekyll front matter to a markdown page."""
    return f"---\nlayout: default\ntitle: {title}\n---\n\n{content}"


def write_markdown_page(src: Path, dst: Path, fallback_title: str, page_kind: str):
    """Copy and rewrite a markdown page into the generated site tree."""
    content = src.read_text(encoding="utf-8")
    title = extract_title(content, fallback_title)
    content = rewrite_links(content, page_kind=page_kind)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(wrap_markdown(content, title), encoding="utf-8")


def write_site_config(output_dir: Path):
    """Write a minimal Jekyll config with nav metadata."""
    config = """title: SnapFS
description: SnapFS client and agent documentation
markdown: kramdown
permalink: pretty
navigation:
  - title: Home
    url: /
  - title: Install
    url: /docs/install/
  - title: Systemd
    url: /docs/systemd/
  - title: Scanner
    url: /docs/scanner/
  - title: Benchmarks
    url: /docs/benchmarks/
"""
    (output_dir / "_config.yml").write_text(config, encoding="utf-8")


def write_layout(output_dir: Path):
    """Write the shared layout for the generated docs site."""
    layout_dir = output_dir / "_layouts"
    layout_dir.mkdir(parents=True, exist_ok=True)
    template = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% if page.title %}{{ page.title }} | {% endif %}{{ site.title }}</title>
    <meta name="description" content="{{ site.description }}">
    <link rel="stylesheet" href="{{ '/assets/site.css' | relative_url }}">
  </head>
  <body>
    <div class="site-shell">
      <header class="site-header">
        <a class="brand" href="{{ '/' | relative_url }}">
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 40 40" role="img" focusable="false">
              <path d="M10 12.5 20 7l10 5.5-10 5.5-10-5.5Z" />
              <path d="M10 20 20 14.5 30 20l-10 5.5L10 20Z" />
              <path d="M10 27.5 20 22l10 5.5L20 33l-10-5.5Z" />
            </svg>
          </span>
          <span>
            <strong>SnapFS</strong>
            <span class="brand-subtitle">repo docs</span>
          </span>
        </a>
        <nav class="site-nav" aria-label="Primary">
          {% for item in site.navigation %}
            <a href="{{ item.url | relative_url }}">{{ item.title }}</a>
          {% endfor %}
          <a href="https://github.com/snapfsio/snapfs">GitHub</a>
          <a href="https://pypi.org/project/snapfs/">PyPI</a>
        </nav>
      </header>
      <main class="site-main">
        {{ content }}
      </main>
    </div>
  </body>
</html>
"""
    (layout_dir / "default.html").write_text(template, encoding="utf-8")


def write_stylesheet(output_dir: Path):
    """Write a dark SnapFS-inspired stylesheet."""
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    css = """:root {
  color-scheme: dark;
  --bg: #0b1220;
  --bg-elevated: #101a2d;
  --panel: rgba(19, 30, 50, 0.92);
  --panel-border: rgba(139, 163, 199, 0.16);
  --text: #e7eefc;
  --muted: #9fb0cd;
  --heading: #f8fbff;
  --accent: #7dd3fc;
  --accent-strong: #38bdf8;
  --shadow: 0 28px 80px rgba(2, 8, 23, 0.48);
}

* { box-sizing: border-box; }

html {
  scroll-behavior: smooth;
}

body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font-family: "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
  line-height: 1.7;
  background:
    radial-gradient(circle at top, rgba(56, 189, 248, 0.16), transparent 34%),
    linear-gradient(180deg, #0b1220 0%, #09111d 100%);
}

a {
  color: var(--accent);
  text-decoration: none;
}

a:hover {
  color: #b6ecff;
}

.site-shell {
  width: min(1100px, calc(100% - 32px));
  margin: 0 auto;
  padding: 24px 0 56px;
}

.site-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 28px;
  padding: 18px 22px;
  border: 1px solid var(--panel-border);
  border-radius: 15px;
  background: rgba(8, 15, 28, 0.72);
  backdrop-filter: blur(18px);
  box-shadow: var(--shadow);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 0.9rem;
  color: var(--heading);
  font-size: 1.4rem;
}

.brand:hover {
  color: var(--heading);
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 15px;
  background: linear-gradient(180deg, rgba(56, 189, 248, 0.22), rgba(125, 211, 252, 0.08));
  color: var(--accent);
}

.brand-mark svg {
  width: 26px;
  height: 26px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linejoin: round;
}

.brand-subtitle {
  margin-left: 0.45rem;
  color: var(--muted);
  font-size: 0.8rem;
  font-weight: 500;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.site-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem;
}

.site-nav a {
  display: inline-flex;
  align-items: center;
  padding: 0.6rem 0.95rem;
  border-radius: 999px;
  color: var(--muted);
}

.site-nav a:hover {
  background: rgba(125, 211, 252, 0.09);
  color: var(--heading);
}

.site-main {
  padding: 0 10px;
}

.site-main h1:first-child,
.site-main p:first-child img {
  margin-top: 0;
}

h1, h2, h3 {
  color: var(--heading);
  line-height: 1.15;
}

h1 {
  font-size: clamp(2rem, 4.8vw, 3.4rem);
  margin: 0 0 1rem;
}

h2 {
  margin-top: 2.6rem;
  font-size: 1.6rem;
}

h3 {
  margin-top: 1.6rem;
  font-size: 1.08rem;
}

p, li {
  color: var(--muted);
  font-size: 1rem;
}

strong {
  color: var(--heading);
}

code, pre {
  font-family: "SFMono-Regular", "Consolas", "Liberation Mono", monospace;
}

code {
  padding: 0.16rem 0.42rem;
  border-radius: 999px;
  background: rgba(125, 211, 252, 0.12);
  color: #c6f4ff;
}

pre {
  overflow-x: auto;
  padding: 1rem 1.15rem 1.1rem;
  border: 1px solid var(--panel-border);
  border-radius: 15px;
  background: #09101c;
}

pre code {
  display: block;
  padding: 0;
  background: transparent;
}

blockquote {
  margin: 1.5rem 0;
  padding: 0.9rem 1.1rem;
  border-left: 4px solid var(--accent);
  background: rgba(19, 30, 50, 0.72);
  color: var(--text);
}

img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 1.5rem 0;
  border: 1px solid var(--panel-border);
  border-radius: 15px;
  box-shadow: var(--shadow);
}

table {
  width: 100%;
  border-collapse: collapse;
  margin: 1.5rem 0;
  background: rgba(19, 30, 50, 0.72);
}

th, td {
  border: 1px solid var(--panel-border);
  padding: 0.75rem 0.85rem;
  text-align: left;
}

th {
  color: var(--heading);
}

@media (max-width: 720px) {
  .site-shell {
    width: min(100%, calc(100% - 20px));
    padding: 18px 0 44px;
  }

  .site-header {
    padding: 16px 18px;
  }

  .site-main {
    padding: 0 4px;
  }
}
"""
    (assets_dir / "site.css").write_text(css, encoding="utf-8")


def build_site(args):
    repo_root = Path(args.repo_root).resolve()
    output_dir = Path(args.output).resolve()

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    write_site_config(output_dir)
    write_layout(output_dir)
    write_stylesheet(output_dir)

    docs_dir = repo_root / "docs"
    home_src = docs_dir / "README.md"
    if home_src.exists():
        write_markdown_page(home_src, output_dir / "index.md", "SnapFS Docs", "root")

    for src in docs_dir.glob("*.md"):
        if src.name == "README.md":
            continue
        dst = output_dir / "docs" / src.name
        fallback = src.stem.replace("-", " ").title()
        write_markdown_page(src, dst, fallback, "docs")

    cname = repo_root / "CNAME"
    if cname.exists():
        shutil.copy2(cname, output_dir / "CNAME")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    build_site(args)


if __name__ == "__main__":
    main()
