#!/usr/bin/env python3
"""Convert raw terminal output (with ANSI codes) to styled HTML.

Usage:
    python agents/ansi_to_html.py agents/s03_example1_raw.txt agents/s03_example1.html

Or pipe:
    printf "prompt\\nq\\n" | python agents/s03_todo_write.py 2>&1 | python agents/ansi_to_html.py - output.html
"""

import html
import re
import sys


ANSI_TO_CSS = {
    "0":  "</span>",
    "1":  '<span class="bold">',
    "2":  '<span class="dim">',
    "31": '<span class="red">',
    "32": '<span class="green">',
    "33": '<span class="yellow">',
    "35": '<span class="magenta">',
    "36": '<span class="cyan">',
}

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{
    background: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Cascadia Code', 'Fira Code', 'Consolas', 'Menlo', monospace;
    font-size: 13px;
    padding: 24px;
    line-height: 1.6;
    max-width: 1200px;
    margin: 0 auto;
  }}
  pre {{
    white-space: pre-wrap;
    word-wrap: break-word;
    margin: 0;
  }}
  .bold    {{ font-weight: bold; }}
  .dim     {{ opacity: 0.6; }}
  .red     {{ color: #f44747; }}
  .green   {{ color: #4ec94e; }}
  .yellow  {{ color: #e5c07b; }}
  .magenta {{ color: #c678dd; }}
  .cyan    {{ color: #56b6c2; }}
</style>
</head>
<body>
<pre>{content}</pre>
</body>
</html>
"""


def convert(raw: str, title: str = "s03 Agent Output") -> str:
    text = html.escape(raw)
    # Replace ANSI escape codes with HTML spans
    def replace_ansi(m):
        code = m.group(1)
        return ANSI_TO_CSS.get(code, "")
    text = re.sub(r"\033\[(\d+)m", replace_ansi, text)
    return HTML_TEMPLATE.format(title=html.escape(title), content=text)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input> <output.html>")
        sys.exit(1)

    infile = sys.argv[1]
    outfile = sys.argv[2]

    if infile == "-":
        raw = sys.stdin.read()
    else:
        with open(infile, "r") as f:
            raw = f.read()

    title = outfile.replace(".html", "").split("/")[-1]
    result = convert(raw, title)

    with open(outfile, "w") as f:
        f.write(result)
    print(f"Wrote {outfile}")
