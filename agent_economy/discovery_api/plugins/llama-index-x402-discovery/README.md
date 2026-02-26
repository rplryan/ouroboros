# llama-index-x402-discovery

LlamaIndex tool for **x402 service discovery** — let your agent find and call any paid API endpoint at runtime without hardcoding URLs or API keys.

When your LlamaIndex agent needs web search, data enrichment, image analysis, or any external capability, it calls `x402_discover` to find the best available service from the live [x402 discovery catalog](https://x402-discovery-api.onrender.com), then calls that endpoint directly using the returned code snippet.

## Installation

```bash
pip install llama-index-x402-discovery
```

## Quick Start

```python
from llama_index.core.agent import ReActAgent
from llama_index.llms.openai import OpenAI
from llama_index_x402_discovery import get_x402_discovery_tool

# Get the x402 FunctionTool
x402_tool = get_x402_discovery_tool()

# Build a ReAct agent with x402 discovery
llm = OpenAI(model="gpt-4o")
agent = ReActAgent.from_tools([x402_tool], llm=llm, verbose=True)

response = agent.chat("Find the cheapest web search API available right now")
print(response)
```

## Full Working Example

```python
from llama_index.core.agent import ReActAgent, FunctionCallingAgent
from llama_index.core.tools import FunctionTool
from llama_index.llms.openai import OpenAI
from llama_index_x402_discovery import get_x402_discovery_tool, x402_discover

# Option 1: Get the pre-built FunctionTool
x402_tool = get_x402_discovery_tool()

# Option 2: Wrap the function yourself with custom metadata
x402_tool = FunctionTool.from_defaults(
    fn=x402_discover,
    name="x402_discover",
    description=(
        "Find paid API services from the x402 catalog. "
        "Call this before using any external API. "
        "Returns endpoint URL, price, and Python usage snippet."
    )
)

# Add to any LlamaIndex agent
llm = OpenAI(model="gpt-4o", temperature=0)

# Works with ReActAgent
agent = ReActAgent.from_tools(
    tools=[x402_tool],
    llm=llm,
    verbose=True,
    system_prompt=(
        "You are an autonomous research assistant. "
        "Before calling any paid API, use x402_discover to find "
        "the best available service and get its endpoint URL and code snippet."
    )
)

# Query the agent
response = agent.chat(
    "I need to extract named entities from text. Find an NLP API that costs less than $0.05/call."
)
print(str(response))
```

## Using with a Query Engine Agent

```python
from llama_index.core.agent import ReActAgent
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.llms.openai import OpenAI
from llama_index_x402_discovery import get_x402_discovery_tool

# Load your documents
documents = SimpleDirectoryReader("./docs").load_data()
index = VectorStoreIndex.from_documents(documents)
query_engine = index.as_query_engine()

# Convert query engine to tool
from llama_index.core.tools import QueryEngineTool
doc_tool = QueryEngineTool.from_defaults(
    query_engine=query_engine,
    name="document_search",
    description="Search internal documents"
)

# Combine with x402 discovery for external APIs
x402_tool = get_x402_discovery_tool()

agent = ReActAgent.from_tools(
    tools=[doc_tool, x402_tool],
    llm=OpenAI(model="gpt-4o"),
    verbose=True
)

response = agent.chat("Summarize our Q3 docs and find a translation API to localize the summary")
print(str(response))
```

## Function Parameters

The `x402_discover` function accepts:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | required | What capability you need (e.g. `'web search'`, `'image generation'`) |
| `max_price_usd` | `float` | `0.50` | Maximum acceptable price per call in USD |
| `network` | `str` | `"base"` | Blockchain network: `base`, `ethereum`, or `solana` |

## Tool Output

Returns a formatted string containing:

- **Service name** and **endpoint URL**
- **Price per call** in USD
- **Uptime %** and **average latency (ms)**
- **Description** of the service
- **Python code snippet** showing how to call the endpoint

Example output:
```
Service: Weather Data Pro
URL: https://api.example.com/weather
Price: $0.002/call
Uptime: 99.9% | Latency: 85ms
Description: Real-time weather data with hourly forecasts
Snippet:
import requests
resp = requests.get("https://api.example.com/weather",
    headers={"X-Payment": "<x402-token>"},
    params={"location": "New York"})
print(resp.json())
```

## Calling x402_discover Directly

You can also call the discovery function directly without building a full agent:

```python
from llama_index_x402_discovery import x402_discover

# Find an image generation service
result = x402_discover(query="image generation", max_price_usd=0.10)
print(result)

# Find a translation API on Ethereum
result = x402_discover(query="text translation", max_price_usd=0.05, network="ethereum")
print(result)
```

## How It Works

1. Agent receives a task requiring an external capability
2. Agent calls `x402_discover` with a description of what it needs
3. The tool fetches the [x402 discovery catalog](https://x402-discovery-api.onrender.com/catalog)
4. Services are filtered by `max_price_usd` and ranked by uptime/latency
5. The best match is returned with endpoint URL and usage code
6. Agent uses the code snippet to call the service directly

## Discovery API

Browse all available services: [https://x402-discovery-api.onrender.com](https://x402-discovery-api.onrender.com)

- `GET /catalog` — List all registered x402 services with quality metrics
- `GET /discover?q=<query>` — Search by capability description
- `GET /health` — API health check

## Links

- [x402 Discovery API](https://x402-discovery-api.onrender.com)
- [GitHub](https://github.com/bazookam7/ouroboros)
- [PyPI](https://pypi.org/project/llama-index-x402-discovery/)
- [Report an issue](https://github.com/bazookam7/ouroboros/issues)

## License

MIT
