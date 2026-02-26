# langchain-x402-discovery

LangChain tool for **x402 service discovery** — let your agent find and call any paid API endpoint at runtime without hardcoding URLs or API keys.

When your LangChain agent needs web search, image generation, data enrichment, or any other external capability, it calls `x402_discover` to find the best available service from the live [x402 discovery catalog](https://x402-discovery-api.onrender.com), then calls that endpoint directly using the returned code snippet.

## Installation

```bash
pip install langchain-x402-discovery
```

## Quick Start

```python
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_x402_discovery import get_x402_discovery_tool

llm = ChatOpenAI(model="gpt-4o")
tools = [get_x402_discovery_tool()]

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant. Use x402_discover to find paid API services when needed."),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

result = executor.invoke({"input": "Find a web search API and tell me the current price per call"})
print(result["output"])
```

## Full Working Example

```python
import os
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_x402_discovery import get_x402_discovery_tool, X402DiscoveryTool

# Option 1: Default tool pointing at the public catalog
tool = get_x402_discovery_tool()

# Option 2: Custom discovery API URL (e.g. a private catalog)
tool = X402DiscoveryTool(
    discovery_api_url="https://x402-discovery-api.onrender.com"
)

# Add to any existing LangChain agent alongside your other tools
llm = ChatOpenAI(model="gpt-4o", temperature=0)

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an autonomous research assistant.

When you need to call any external API — web search, data enrichment, image analysis,
translation, or any other capability — first call x402_discover with a short description
of what you need. It will return the endpoint URL, price, and a Python code snippet.
Use that snippet to make the actual API call.

Always prefer the x402 catalog over hardcoded APIs."""),
    MessagesPlaceholder("chat_history", optional=True),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

agent = create_tool_calling_agent(llm, [tool], prompt)
executor = AgentExecutor(agent=agent, tools=[tool], verbose=True, max_iterations=5)

# The agent autonomously discovers and uses paid API services
response = executor.invoke({
    "input": "I need to analyze sentiment in 50 customer reviews. Find the cheapest API for this."
})
print(response["output"])
```

## Tool Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | required | Natural language description of the capability needed |
| `max_price_usd` | `float` | `0.50` | Maximum acceptable price per call in USD |
| `network` | `str` | `"base"` | Blockchain network: `base`, `ethereum`, or `solana` |

## Tool Output

The tool returns a formatted string containing:

- **Service name** and **endpoint URL**
- **Price per call** in USD
- **Uptime %** and **average latency (ms)** — quality signals for routing
- **Description** of the service
- **Python code snippet** showing exactly how to call the endpoint

Example output:
```
Found: SerpAPI Proxy
URL: https://api.example.com/search
Price: $0.01/call
Uptime: 99.7%
Latency: 210ms
Description: Google Search results via x402 micropayment

Python snippet:
import requests
resp = requests.post("https://api.example.com/search",
    headers={"X-Payment": "<x402-token>"},
    json={"q": "your query"})
print(resp.json())
```

## Adding to an Existing Agent

If you already have a LangChain agent with other tools, just append the discovery tool:

```python
from langchain_x402_discovery import get_x402_discovery_tool

# Your existing tools
existing_tools = [my_calculator_tool, my_file_tool]

# Add x402 discovery
tools = existing_tools + [get_x402_discovery_tool()]

# Rebuild your agent with the extended tool list
agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools)
```

## Using with LCEL (LangChain Expression Language)

```python
from langchain_x402_discovery import get_x402_discovery_tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

llm = ChatOpenAI(model="gpt-4o")
tool = get_x402_discovery_tool()
llm_with_tools = llm.bind_tools([tool])

messages = [HumanMessage("Find an image generation API under $0.10/call")]
response = llm_with_tools.invoke(messages)

# Handle tool call if present
if response.tool_calls:
    tool_result = tool.invoke(response.tool_calls[0]["args"])
    print(tool_result)
```

## How It Works

1. Your agent receives a task requiring an external API (e.g., "search the web for X")
2. Agent calls `x402_discover` with a natural language query (e.g., "web search")
3. The tool fetches the [x402 discovery catalog](https://x402-discovery-api.onrender.com/catalog)
4. Services are filtered by `max_price_usd` and ranked by uptime/latency
5. The best match is returned with endpoint URL and a ready-to-use code snippet
6. Agent uses the snippet to call the service and complete the task

## Discovery API

Browse all available services: [https://x402-discovery-api.onrender.com](https://x402-discovery-api.onrender.com)

- `GET /catalog` — List all registered x402 services with quality metrics
- `GET /discover?q=<query>` — Search services by natural language capability
- `GET /health` — API health check

## Links

- [x402 Discovery API](https://x402-discovery-api.onrender.com)
- [GitHub](https://github.com/bazookam7/ouroboros)
- [PyPI](https://pypi.org/project/langchain-x402-discovery/)
- [Report an issue](https://github.com/bazookam7/ouroboros/issues)

## License

MIT
