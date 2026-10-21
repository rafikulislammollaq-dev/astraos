#!/usr/bin/env python3
"""Build the offline help centre from the corpus the assistant already ships.

The project already carries the answers: `knowledge/` holds the how-do-I pages and
`skills/` holds the procedures, each with a keywords line. They are written for
the assistant to use, but a person reading them in a text editor is a person the
OS has not helped yet.

This script turns that corpus into one self-contained HTML file:

  * no network, no fonts, no scripts from anywhere else - it works from a file://
    URL on a machine with no connection at all, which is the point of an offline
    help centre;
  * every topic is in the page, so the search works with the machine offline;
  * the search box filters on the title, the keywords and the body, so "printer",
    "dns" or "phone" find their page.

The generated file is committed (like the generated branding assets), and a static
test regenerates it and compares, so the page can never drift from the corpus.

Usage:
    scripts/build-help-center.py [--corpus DIR] [--out FILE]

Exit codes:
    0  the page was written
    2  the corpus directory does not exist or holds no topics
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "share" / "astraos" / "ai"
DEFAULT_OUT = DEFAULT_CORPUS / "web" / "help.html"

# The palette is the distribution's own (config/branding.env): the help centre
# should look like the system it explains.
STYLE = """
:root {
  --bg: #12141A;
  --panel: #05030A;
  --text: #E8ECF2;
  --muted: #9AA3B2;
  --accent: #22E6FF;
  --accent-2: #8B3DFF;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.55 system-ui, "DejaVu Sans", sans-serif;
}
header {
  position: sticky; top: 0; z-index: 5; padding: 18px 22px 14px;
  background: linear-gradient(180deg, var(--panel), rgba(5,3,10,.92));
  border-bottom: 1px solid #262A35;
}
h1 { margin: 0 0 4px; font-size: 19px; letter-spacing: .3px; }
header p { margin: 0 0 12px; color: var(--muted); font-size: 13px; }
#search {
  width: 100%; max-width: 640px; padding: 10px 13px; font-size: 15px;
  color: var(--text); background: #1B1F29; border: 1px solid #313747; border-radius: 8px;
}
#search:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
main { display: grid; grid-template-columns: 290px 1fr; gap: 22px; padding: 22px; align-items: start; }
nav { position: sticky; top: 120px; max-height: calc(100vh - 140px); overflow: auto; }
nav h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .12em; color: var(--muted); margin: 14px 4px 6px; }
nav a { display: block; padding: 6px 9px; border-radius: 6px; color: var(--text); text-decoration: none; font-size: 14px; }
nav a:hover, nav a:focus { background: #1B1F29; color: var(--accent); outline: none; }
nav a[hidden] { display: none; }
article { background: var(--panel); border: 1px solid #232733; border-radius: 12px; padding: 22px 26px; }
article[hidden] { display: none; }
article h1 { font-size: 24px; margin: 0 0 6px; }
article h2 { font-size: 17px; margin: 22px 0 8px; color: var(--accent); }
article h3 { font-size: 15px; margin: 16px 0 6px; color: var(--accent-2); }
article p { margin: 9px 0; }
article li { margin: 4px 0; }
code { background: #1B1F29; border: 1px solid #2A2F3C; border-radius: 5px; padding: 1px 5px; font-family: "DejaVu Sans Mono", monospace; font-size: 13px; white-space: pre-wrap; }
pre { background: #0B0D13; border: 1px solid #2A2F3C; border-radius: 8px; padding: 12px 14px; overflow: auto; }
pre code { background: none; border: none; padding: 0; }
a { color: var(--accent); }
.when { border-left: 3px solid var(--accent-2); background: #151020; padding: 9px 13px; border-radius: 0 8px 8px 0; margin: 10px 0 4px; color: #D8CCFF; font-size: 14px; }
.keywords { color: var(--muted); font-size: 12.5px; margin: 2px 0 14px; }
footer { padding: 20px 22px 40px; color: var(--muted); font-size: 13px; max-width: 760px; }
#count { color: var(--muted); font-size: 13px; margin-top: 10px; }
@media (max-width: 780px) { main { grid-template-columns: 1fr; } nav { position: static; max-height: none; } }
"""

SCRIPT = """
(function () {
  var topics = window.ASTRAOS_HELP_TOPICS || [];
  var search = document.getElementById('search');
  var count = document.getElementById('count');
  var nav = document.getElementById('topics');
  var articles = document.getElementById('articles');

  function haystack(topic) {
    return (topic.title + ' ' + topic.keywords + ' ' + topic.when + ' ' + topic.text).toLowerCase();
  }

  function apply() {
    var query = search.value.trim().toLowerCase();
    var words = query ? query.split(/\\s+/) : [];
    var shown = 0;
    topics.forEach(function (topic) {
      var text = haystack(topic);
      var match = words.every(function (word) { return text.indexOf(word) !== -1; });
      var link = nav.querySelector('[data-topic="' + topic.id + '"]');
      var article = document.getElementById(topic.id);
      if (link) { link.hidden = !match; }
      if (article) { article.hidden = !match; }
      if (match) { shown += 1; }
    });
    count.textContent = shown === topics.length
      ? topics.length + ' topics'
      : shown + ' of ' + topics.length + ' topics match';
  }

  search.addEventListener('input', apply);
  apply();
})();
"""


def _topics(corpus: Path) -> list[dict]:
    """Read the corpus: the knowledge pages and the skills, in that order."""
    topics: list[dict] = []

    knowledge = corpus / "knowledge"
    if knowledge.is_dir():
        for path in sorted(knowledge.glob("*.md")):
            topics.append(_topic_from(path, kind="knowledge"))

    skills = corpus / "skills"
    if skills.is_dir():
        for path in sorted(skills.glob("*/SKILL.md")):
            topics.append(_topic_from(path, kind="skill"))

    return [topic for topic in topics if topic]


def _topic_from(path: Path, kind: str) -> dict | None:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    title = ""
    keywords = ""
    when = ""
    body_start = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            body_start = index + 1
            continue
        if stripped.lower().startswith("keywords:"):
            keywords = stripped.split(":", 1)[1].strip()
            body_start = max(body_start, index + 1)
            continue
        if stripped.lower().startswith("when:") and kind == "skill":
            when = stripped.split(":", 1)[1].strip()
            body_start = max(body_start, index + 1)
            continue
        if not title:
            title = path.stem.replace("-", " ").capitalize()
            body_start = index

    body = "\n".join(lines[body_start:]).strip()
    if not body:
        return None
    body_html = _markdown(body)
    text = re.sub(r"<[^>]+>", " ", body_html)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", (title or path.stem).lower()).strip("-"),
        "title": title,
        "kind": kind,
        "keywords": keywords,
        "when": when,
        "html": body_html,
        "text": text,
        "source": path.name,
    }


def _inline(text: str) -> str:
    """Inline markdown: bold, italic, links.

    Inline code is already stashed by _markdown() before the line pass (a code
    span in this corpus sometimes wraps onto the next line), so the placeholders
    pass through here untouched.
    """
    text = html.escape(text)

    def link(match: re.Match) -> str:
        label, target = match.group(1), match.group(2)
        if re.match(r"^(https?|file):", target, re.I):
            return f'<a href="{html.escape(target, quote=True)}">{label}</a>'
        return label

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    return text


def _markdown(text: str) -> str:
    """A small, honest markdown subset: what this corpus actually uses."""
    # Inline code is pulled out before the line-by-line pass, because a code span
    # in this corpus sometimes wraps onto the next line (a long cmake invocation
    # split for width). Handling it per line would leave the backticks visible.
    spans: list[str] = []

    def stash_code(match: re.Match) -> str:
        spans.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash_code, text, flags=re.S)

    out: list[str] = []
    in_code = False
    code_lines: list[str] = []
    list_type = ""

    for raw in text.splitlines():
        if raw.strip().startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(raw)
            continue

        stripped = raw.strip()
        if not stripped:
            if list_type:
                out.append(f"</{list_type}>")
                list_type = ""
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            if list_type:
                out.append(f"</{list_type}>")
                list_type = ""
            level = min(len(heading.group(1)) + 1, 4)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        ordered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if bullet or ordered:
            wanted = "ul" if bullet else "ol"
            if list_type != wanted:
                if list_type:
                    out.append(f"</{list_type}>")
                out.append(f"<{wanted}>")
                list_type = wanted
            content = (bullet or ordered).group(1)
            out.append(f"<li>{_inline(content)}</li>")
            continue

        if list_type:
            out.append(f"</{list_type}>")
            list_type = ""
        out.append(f"<p>{_inline(stripped)}</p>")

    if in_code and code_lines:
        out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    if list_type:
        out.append(f"</{list_type}>")
    rendered = "\n".join(out)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], rendered)


def _page(topics: list[dict]) -> str:
    nav_parts: list[str] = []
    article_parts: list[str] = []
    knowledge: list[dict] = [t for t in topics if t["kind"] == "knowledge"]
    skills: list[dict] = [t for t in topics if t["kind"] == "skill"]

    def group(heading: str, items: list[dict]) -> None:
        if not items:
            return
        nav_parts.append(f"<h2>{html.escape(heading)}</h2>")
        for topic in items:
            nav_parts.append(
                f'<a href="#{topic["id"]}" data-topic="{topic["id"]}">{html.escape(topic["title"])}</a>'
            )

    group("How do I ...", knowledge)
    group("Tasks the assistant can do", skills)

    for topic in topics:
        meta = ""
        if topic["when"]:
            meta += f'<div class="when"><strong>Use this when:</strong> {html.escape(topic["when"])}</div>'
        if topic["keywords"]:
            meta += f'<div class="keywords">Keywords: {html.escape(topic["keywords"])}</div>'
        article_parts.append(
            f'<article id="{topic["id"]}"><h1>{html.escape(topic["title"])}</h1>{meta}'
            f'{topic["html"]}</article>'
        )

    payload = json.dumps(
        [
            {
                "id": topic["id"],
                "title": topic["title"],
                "keywords": topic["keywords"],
                "when": topic["when"],
                "text": topic["text"],
            }
            for topic in topics
        ],
        ensure_ascii=False,
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AstraOS Help</title>
<style>{STYLE}</style>
</head>
<body>
<header>
  <h1>AstraOS Help</h1>
  <p>Everything here is written for this system and stored on this machine. No connection is needed.</p>
  <input id="search" type="search" placeholder="What do you want to do? Try: printer, dns, phone, backup" aria-label="Search the help topics">
  <div id="count"></div>
</header>
<main>
  <nav id="topics" aria-label="Help topics">
{chr(10).join(nav_parts)}
  </nav>
  <div id="articles">
{chr(10).join(article_parts)}
  </div>
</main>
<footer>
  <p>These are the same pages the assistant reads when you ask it something, written out so
  you can read them without asking. They cover {len(knowledge)} task(s) and {len(skills)} of the
  assistant's procedures, and they ship with the image.</p>
  <p>Nothing on this page is fetched from the network, and nothing here leaves the machine.</p>
</footer>
<script>window.ASTRAOS_HELP_TOPICS = {payload};</script>
<script>{SCRIPT}</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="the knowledge/skills directory")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="where to write the page")
    args = parser.parse_args(argv)

    corpus = Path(args.corpus)
    if not corpus.is_dir():
        print(f"ERROR: no corpus directory: {corpus}", file=sys.stderr)
        return 2
    topics = _topics(corpus)
    if not topics:
        print(f"ERROR: the corpus holds no topics: {corpus}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    page = _page(topics)
    # newline="\n" so the file is byte-identical wherever it is generated: a page
    # that differs between a Windows checkout and a Linux build is a page nobody can
    # reproduce.
    out.write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(topics)} topic(s), {len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
