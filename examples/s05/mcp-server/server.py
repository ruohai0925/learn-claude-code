#!/usr/bin/env python3
"""
File & Utilities MCP Server
Provides Claude with tools for file operations, text processing, and system info.
"""

import asyncio
import os
import json
import hashlib
import platform
import datetime
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# ── Server instance ────────────────────────────────────────────────────────────
mcp = FastMCP("file-utilities-server")

# ── TOOLS ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def read_file(path: str) -> str:
    """Read the contents of a file from disk.

    Args:
        path: Absolute or relative path to the file.
    """
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Error: File not found — {p}"
        if not p.is_file():
            return f"Error: Path is not a file — {p}"
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write (or overwrite) a file with the given content.

    Args:
        path: Absolute or relative path to the file.
        content: Text content to write.
    """
    try:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {p}"
    except Exception as e:
        return f"Error writing file: {e}"


@mcp.tool()
def list_directory(path: str = ".") -> str:
    """List files and directories at the given path.

    Args:
        path: Directory to list. Defaults to current directory.
    """
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Error: Path not found — {p}"
        if not p.is_dir():
            return f"Error: Path is not a directory — {p}"

        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        lines = [f"Contents of {p}:", ""]
        for entry in entries:
            kind = "FILE" if entry.is_file() else "DIR "
            size = f"{entry.stat().st_size:>10,} B" if entry.is_file() else " " * 12
            lines.append(f"  [{kind}] {size}  {entry.name}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing directory: {e}"


@mcp.tool()
def file_info(path: str) -> str:
    """Get detailed metadata about a file or directory.

    Args:
        path: Path to inspect.
    """
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Error: Path not found — {p}"

        stat = p.stat()
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
        ctime = datetime.datetime.fromtimestamp(stat.st_ctime).isoformat()
        info = {
            "path": str(p),
            "type": "file" if p.is_file() else "directory",
            "size_bytes": stat.st_size,
            "modified": mtime,
            "created": ctime,
            "suffix": p.suffix,
        }
        if p.is_file():
            md5 = hashlib.md5(p.read_bytes()).hexdigest()
            info["md5"] = md5
        return json.dumps(info, indent=2)
    except Exception as e:
        return f"Error getting file info: {e}"


@mcp.tool()
def search_in_files(directory: str, keyword: str, extension: str = "") -> str:
    """Search for a keyword across all text files in a directory.

    Args:
        directory: Root directory to search.
        keyword: Text to search for (case-insensitive).
        extension: Optional file extension filter, e.g. ".py" or ".txt".
    """
    try:
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            return f"Error: Not a directory — {root}"

        matches = []
        pattern = f"*{extension}" if extension else "*"
        for file in root.rglob(pattern):
            if not file.is_file():
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(text.splitlines(), 1):
                    if keyword.lower() in line.lower():
                        rel = file.relative_to(root)
                        matches.append(f"{rel}:{i}  {line.strip()}")
            except Exception:
                continue

        if not matches:
            return f"No matches found for '{keyword}' in {root}"
        header = f"Found {len(matches)} match(es) for '{keyword}' in {root}:\n"
        return header + "\n".join(matches[:100])  # cap at 100 results
    except Exception as e:
        return f"Error searching files: {e}"


@mcp.tool()
def word_count(text: str) -> str:
    """Count words, lines, and characters in a block of text.

    Args:
        text: The text to analyse.
    """
    lines = text.splitlines()
    words = text.split()
    result = {
        "characters": len(text),
        "characters_no_spaces": len(text.replace(" ", "").replace("\n", "")),
        "words": len(words),
        "lines": len(lines),
        "paragraphs": len([l for l in lines if l.strip()]),
    }
    return json.dumps(result, indent=2)


@mcp.tool()
def json_format(json_string: str, indent: int = 2) -> str:
    """Parse and pretty-print a JSON string.

    Args:
        json_string: Raw JSON to format.
        indent: Number of spaces for indentation (default 2).
    """
    try:
        data = json.loads(json_string)
        return json.dumps(data, indent=indent, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"


@mcp.tool()
def system_info() -> str:
    """Return basic information about the host system."""
    info = {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
        "cwd": os.getcwd(),
        "home": str(Path.home()),
        "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
    }
    return json.dumps(info, indent=2)


@mcp.tool()
def calculate(expression: str) -> str:
    """Safely evaluate a mathematical expression.

    Args:
        expression: A Python math expression, e.g. "2 ** 10 + 42 / 7"
    """
    import math

    allowed_names = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
    allowed_names.update({"abs": abs, "round": round, "min": min, "max": max})

    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)  # noqa: S307
        return str(result)
    except Exception as e:
        return f"Calculation error: {e}"


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
