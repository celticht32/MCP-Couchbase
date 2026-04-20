Couchbase MCP Server

A Python MCP (Model Context Protocol) server that exposes Couchbase operations as tools for AI assistants like Claude.

Features

CRUD	`cb\_get`, `cb\_upsert`, `cb\_insert`, `cb\_replace`, `cb\_delete`, `cb\_get\_multi`
N1QL / SQL++	`cb\_query` (with named parameters)
Full-Text Search	`cb\_fts\_search` (match query, fields, highlighting)
Utility	`cb\_ping`


Quick Start
1. Install dependencies
```bash
pip install -r requirements.txt
```

Requires Python 3.10+ and a running Couchbase Server (7.x+).

2. Configure environment variables
Variable	Default	Description
`CB\_CONNECTION\_STRING`	`couchbase://localhost`	Cluster connection string
`CB\_USERNAME`	`Administrator`	Auth username
`CB\_PASSWORD`	`password`	Auth password
`CB\_BUCKET`	`default`	Default bucket
`CB\_SCOPE`	`\_default`	Default scope
`CB\_COLLECTION`	`\_default`	Default collection
You can export them directly or supply them in the MCP config (see step 3).

3. Register with Claude Desktop
Edit `\~/Library/Application Support/Claude/claude\_desktop\_config.json` (macOS) or `%APPDATA%\\Claude\\claude\_desktop\_config.json` (Windows) and merge in:
```json
{
  "mcpServers": {
    "couchbase": {
      "command": "python",
      "args": \["/absolute/path/to/couchbase-mcp-server/server.py"],
      "env": {
        "CB\_CONNECTION\_STRING": "couchbase://localhost",
        "CB\_USERNAME": "Administrator",
        "CB\_PASSWORD": "password",
        "CB\_BUCKET": "travel-sample",
        "CB\_SCOPE": "\_default",
        "CB\_COLLECTION": "\_default"
      }
    }
  }
}
```
Restart Claude Desktop. The Couchbase tools will appear automatically.
---
Tool Reference
`cb\_get`
```json
{ "key": "airline\_10" }
```
`cb\_upsert`
```json
{
  "key": "user::alice",
  "document": { "name": "Alice", "email": "alice@example.com" }
}
```
`cb\_insert` / `cb\_replace`
Same schema as `cb\_upsert`. `insert` fails if the key exists; `replace` fails if it doesn't.
`cb\_delete`
```json
{ "key": "user::alice" }
```
`cb\_get\_multi`
```json
{ "keys": \["airline\_10", "airline\_11", "airline\_12"] }
```
`cb\_query`
```json
{
  "statement": "SELECT name, country FROM `travel-sample`.inventory.airline WHERE country = $country LIMIT 5",
  "params": { "country": "United States" },
  "readonly": true
}
```
`cb\_fts\_search`
```json
{
  "index\_name": "travel-search",
  "query": "San Francisco airport",
  "limit": 5,
  "fields": \["name", "city", "country"],
  "highlight": true
}
```
`cb\_ping`
```json
{}
```
---

Connecting to Couchbase Capella (Cloud)
Use the connection string from your Capella console and enable TLS:

CB\_CONNECTION\_STRING=couchbases://cb.xxxx.cloud.couchbase.com

Note the `couchbases://` scheme (TLS). Capella requires certificates which the SDK handles automatically.

Running standalone (for testing)
```bash
CB\_CONNECTION\_STRING=couchbase://localhost \\
CB\_USERNAME=Administrator \\
CB\_PASSWORD=password \\
CB\_BUCKET=travel-sample \\
python server.py
```
The server communicates over stdio per the MCP spec — use an MCP client or Claude Desktop to interact with it.
