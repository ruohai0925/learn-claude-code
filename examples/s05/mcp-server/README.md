# File & Utilities MCP Server

A Python MCP server that gives Claude tools for **file operations**, **text
processing**, and **system utilities**.

---

## Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read the contents of any text file |
| `write_file` | Write (or overwrite) a file |
| `list_directory` | List files & folders at a path |
| `file_info` | Metadata + MD5 checksum for a file/dir |
| `search_in_files` | Grep-style keyword search across files |
| `word_count` | Count words, lines, chars in text |
| `json_format` | Pretty-print a JSON string |
| `system_info` | OS, Python version, hostname, CWD |
| `calculate` | Safely evaluate a math expression |

---

## Setup

```bash
# 1. Create and activate a virtual environment
cd mcp-server
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install mcp httpx
```

---

## Register with Claude Desktop

Add the following to `~/.claude/mcp.json` (create the file if it doesn't
exist):

```json
{
  "mcpServers": {
    "file-utilities": {
      "command": "/home/yzeng/Codes/learn-claude-code/mcp-server/venv/bin/python3",
      "args": ["/home/yzeng/Codes/learn-claude-code/mcp-server/server.py"]
    }
  }
}
```

Then restart Claude Desktop — the tools will appear automatically.

---

## Testing manually

```bash
# List all available tools
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | venv/bin/python3 server.py

# Call a tool
echo '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"system_info","arguments":{}}}' \
  | venv/bin/python3 server.py
```

---

## Project Structure

```
mcp-server/
├── server.py      ← MCP server (all tools defined here)
├── README.md      ← This file
└── venv/          ← Python virtual environment
```

---

## Extending the Server

Add a new tool in `server.py` using the `@server.tool()` decorator:

```python
@server.tool()
async def my_tool(param: str) -> str:
    """Short description shown to Claude.

    Args:
        param: What this parameter does.
    """
    return f"Result for: {param}"
```

No registration needed — the decorator handles everything.
