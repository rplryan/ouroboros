# x402 Discovery MCP Server

A local MCP server that exposes the [x402 Service Discovery API](https://x402-discovery-api.onrender.com) as native tools in Claude Desktop, Cursor, Windsurf, and any MCP-compatible host.

## Tools

| Tool | Description |
|---|---|
| `x402_discover` | Quality-ranked search — find the best service for a capability |
| `x402_browse` | Free catalog overview, grouped by category |
| `x402_health` | Live health check for a specific service |
| `x402_register` | Register your own x402 endpoint |

## Installation

```bash
pip install mcp requests
# or
pip install -r requirements.txt
```

## Add to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "x402-discovery": {
      "command": "python",
      "args": ["/absolute/path/to/agent_economy/discovery_api/mcp/server.py"]
    }
  }
}
```

Restart Claude Desktop. You will see the x402 tools appear in the tool selector.

## Add to Cursor

Open Cursor Settings → Features → MCP Servers → Add Server:

```json
{
  "x402-discovery": {
    "command": "python",
    "args": ["/absolute/path/to/agent_economy/discovery_api/mcp/server.py"]
  }
}
```

Or edit `~/.cursor/mcp.json` directly:

```json
{
  "mcpServers": {
    "x402-discovery": {
      "command": "python",
      "args": ["/absolute/path/to/agent_economy/discovery_api/mcp/server.py"]
    }
  }
}
```

## Add to Windsurf

Edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "x402-discovery": {
      "command": "python",
      "args": ["/absolute/path/to/agent_economy/discovery_api/mcp/server.py"]
    }
  }
}
```

## Run directly (for testing)

```bash
python server.py
```

The server communicates over stdio. When run directly you can send MCP protocol messages on stdin.

## Example interaction

Once connected, Claude can use the tools naturally:

> "Find me a research API under $0.10 per call"
> → Claude calls `x402_discover(capability="research", max_price_usd=0.10)`

> "Is the ouroboros/discovery service online?"
> → Claude calls `x402_health(service_id="ouroboros/discovery")`

## Using the hosted HTTP endpoint instead

If you prefer not to run a local process, you can also point directly at the hosted MCP endpoint:

```json
{
  "mcpServers": {
    "x402-discovery": {
      "url": "https://x402-discovery-api.onrender.com/mcp"
    }
  }
}
```

Note: the hosted endpoint serves the MCP tool manifest only. The local server (`server.py`) provides full tool execution.

---

## x402 Payment Gateway (`x402_gateway.py`)

### What it is

`x402_gateway.py` is the convergence of two protocols: **x402** (HTTP micropayments) and **MCP** (Model Context Protocol tool calls). Every tool call through this server requires a USDC micropayment on Base before it executes — creating a programmable tool economy where agents automatically pay for capabilities.

This pattern doesn't exist elsewhere in the ecosystem. `server.py` is a *discovery client* (free, read-only). `x402_gateway.py` is a *payment gate* — every tool call is a paid transaction.

```
MCP Client (Claude / Cursor / any agent)
    ↓  tool call (no payment)
x402_gateway
    ↓  returns payment challenge (402 equivalent)
Agent pays USDC on Base, gets payment proof
    ↓  tool call with x402_payment=<proof>
x402_gateway verifies proof with x402.org/facilitator
    ↓  verified
Tool executes, result returned to agent
```

### Two servers at a glance

| | `server.py` | `x402_gateway.py` |
|---|---|---|
| Purpose | Discovery client | Payment gate |
| Cost per call | Free | USDC micropayment |
| Tools | x402_discover, x402_browse, x402_health, x402_register | list_gated_tools, discover_x402_services, gateway_stats, register_tool_for_payment |
| Use case | Find services | Sell / buy tool access |

### Installation

```bash
pip install mcp requests httpx
# or
pip install -r requirements.txt
```

### Running

```bash
python x402_gateway.py
```

The server starts on stdio (MCP standard). Set `GATEWAY_PORT` to expose over HTTP if needed.

### Adding to Claude Desktop

```json
{
  "mcpServers": {
    "x402-gateway": {
      "command": "python",
      "args": ["/absolute/path/to/agent_economy/discovery_api/mcp/x402_gateway.py"]
    }
  }
}
```

### Payment flow

1. **Call any gated tool without `x402_payment`** — the server returns a JSON payment challenge:
   ```json
   {
     "error": "Payment Required",
     "x402Version": 2,
     "tool": "discover_x402_services",
     "accepts": [{
       "scheme": "exact",
       "network": "eip155:8453",
       "amount": "1000",
       "payTo": "0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA",
       "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
     }]
   }
   ```
2. **Pay the specified amount** in USDC on Base to the `payTo` address.
3. **Call the tool again** with `x402_payment=<your_payment_proof>`.
4. The gateway verifies your proof with `https://x402.org/facilitator/verify`.
5. If valid, the tool executes and returns its result.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `WALLET_ADDRESS` | CDP wallet address | USDC recipient for all payments |
| `GATEWAY_PORT` | `8080` | HTTP port (if running in HTTP mode) |
| `X402_DEV_MODE` | unset | Set to `1` to skip payment verification (testing only) |

### Built-in tools

| Tool | Paid? | Description |
|---|---|---|
| `list_gated_tools` | Free | List all registered tools and their prices |
| `gateway_stats` | Free | Total calls, revenue, per-tool breakdown |
| `discover_x402_services` | $0.001/call | Find x402 services by capability |
| `register_tool_for_payment` | Free | Register an external endpoint behind the payment gate |

### Registering your own tools

Call `register_tool_for_payment` from any MCP client:

```
register_tool_for_payment(
    tool_name="weather_lookup",
    description="Current weather for any city.",
    price_usdc_units=500,          # $0.0005 per call
    endpoint_url="https://my-api.example.com/weather",
    tags="weather,data"
)
```

After registration, any agent calling `weather_lookup` through this gateway will be gated behind a $0.0005 USDC payment — and your endpoint receives the call only after payment is verified.
