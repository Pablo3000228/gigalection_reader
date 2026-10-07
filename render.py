"""Конспекты Markdown -> HTML с формулами (KaTeX). Открывать в браузере.

Запуск:
    python render.py              # все конспект*.md в output/
    python render.py путь.md      # один файл
"""

import html
import re
import sys
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

ROOT = Path(__file__).resolve().parent
KATEX = "https://cdn.jsdelivr.net/npm/katex@0.16.22/dist"

TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{katex}/katex.min.css">
<script defer src="{katex}/katex.min.js"></script>
<script defer src="{katex}/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body, {{delimiters: [
    {{left: '\\\\[', right: '\\\\]', display: true}},
    {{left: '\\\\(', right: '\\\\)', display: false}}], throwOnError: false}})"></script>
<style>
  :root {{ --bg:#fff; --fg:#1f2328; --muted:#59636e; --line:#d1d9e0; --soft:#f6f8fa; --note:#eef6ff; --accent:#0969da; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --line:#3d444d; --soft:#151b23; --note:#0f2238; --accent:#4493f8; }}
  }}
  body {{ background:var(--bg); color:var(--fg); font:16px/1.65 system-ui, "Segoe UI", sans-serif;
         max-width:860px; margin:0 auto; padding:24px 16px 64px; }}
  h1 {{ font-size:1.7em; line-height:1.25; }}
  h2 {{ border-bottom:1px solid var(--line); padding-bottom:.25em; margin-top:2em; }}
  code {{ background:var(--soft); padding:.1em .35em; border-radius:4px; font-size:.85em; color:var(--muted); }}
  blockquote {{ margin:1em 0; padding:.6em 1em; background:var(--note); border-left:4px solid var(--accent); border-radius:6px; }}
  blockquote p {{ margin:.4em 0; }}
  table {{ border-collapse:collapse; width:100%; display:block; overflow-x:auto; }}
  th, td {{ border:1px solid var(--line); padding:6px 10px; vertical-align:top; }}
  th {{ background:var(--soft); }}
  img {{ max-width:100%; border:1px solid var(--line); border-radius:6px; }}
  hr {{ border:0; border-top:2px dashed var(--line); margin:3em 0; }}
  .katex-display {{ overflow-x:auto; overflow-y:hidden; padding:.2em 0; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def wikilinks_to_md(text: str) -> str:
    """Obsidian-ссылки на заголовки [[#Заголовок|текст]] -> [текст](#id)."""
    def repl(m: re.Match) -> str:
        target, alias = m.group(1), m.group(2) or m.group(1)
        return f"[{alias}](#{slugify_unicode(target, '-')})"
    return re.sub(r"\[\[#([^\]|]+)(?:\|([^\]]+))?\]\]", repl, text)


def render(md_path: Path) -> Path:
    text = md_path.read_text(encoding="utf-8")
    body = markdown.markdown(
        wikilinks_to_md(text),
        extensions=["tables", "sane_lists", "toc", "pymdownx.arithmatex"],
        extension_configs={
            "pymdownx.arithmatex": {"generic": True},
            "toc": {"slugify": slugify_unicode},
        },
    )
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), md_path.stem)
    out = md_path.with_suffix(".html")
    out.write_text(TEMPLATE.format(title=html.escape(title), katex=KATEX, body=body), encoding="utf-8")
    return out


def main() -> None:
    files = [Path(a) for a in sys.argv[1:]] or sorted((ROOT / "output").rglob("конспект*.md"))
    for f in files:
        print(render(f))


if __name__ == "__main__":
    main()
