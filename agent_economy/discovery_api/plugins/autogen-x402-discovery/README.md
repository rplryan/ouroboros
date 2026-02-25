# autogen-x402-discovery

AutoGen tool for **x402 service discovery** — let your AutoGen agents find and call any paid API endpoint at runtime without hardcoding URLs or API keys.

Register `x402_discover` on any `ConversableAgent` and it can autonomously locate web search, data enrichment, image analysis, or any other external service from the live [x402 discovery catalog](https://x402-discovery-api.onrender.com).

## Installation

```bash
pip install autogen-x402-discovery
```

## Quick Start

```python
import autogen
from autogen_x402_discovery import x402_discover, register_with_autogen

config_list = [{"model": "gpt-4o", "api_key": "YOUR_OPENAI_API_KEY"}]

# Create an assistant agent
assistant = autogen.AssistantAgent(
    name="assistant",
    llm_config={"config_list": config_list},
    system_message="You are a helpful assistant. Use x402_discover to find paid API services."
)

# Register the discovery function on the agent
register_with_autogen(assistant)

# Create a user proxy
user_proxy = autogen.UserProxyAgent(
    name="user_proxy",
    human_input_mode="NEVER",
    max_consecutive_auto_reply=5,
    code_execution_config={"work_dir": "workspace", "use_docker": False},
)

# Register on user proxy too (required for AutoGen tool execution)
user_proxy.register_for_execution(name="x402_discover")(x402_discover)

user_proxy.initiate_chat(
    assistant,
    message="Find the best web search API under $0.05/call and tell me its endpoint URL."
)
```

## Full Working Example — Multi-Agent Research Team

```python
import autogen
from autogen_x402_discovery import x402_discover, register_with_autogen

config_list = [{"model": "gpt-4o", "api_key": "YOUR_OPENAI_API_KEY"}]
llm_config = {"config_list": config_list, "timeout": 60}

# Research agent that discovers and uses external APIs
researcher = autogen.AssistantAgent(
    name="Researcher",
    llm_config=llm_config,
    system_message="""You are an autonomous research agent.
When you need any external data or API capability, call x402_discover first
to find the best available service. Then use the returned endpoint URL and
code snippet to fetch the data. Report your findings clearly."""
)

# Analyst agent (no tools needed)
analyst = autogen.AssistantAgent(
    name="Analyst",
    llm_config=llm_config,
    system_message="You analyze data provided by the Researcher and summarize key insights."
)

# User proxy that executes code and tool calls
user_proxy = autogen.UserProxyAgent(
    name="UserProxy",
    human_input_mode="NEVER",
    max_consecutive_auto_reply=10,
    code_execution_config={"work_dir": "workspace", "use_docker": False},
    is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("TERMINATE")
)

# Register x402_discover on both agents
register_with_autogen(researcher)
user_proxy.register_for_execution(name="x402_discover")(x402_discover)

# Start the conversation
user_proxy.initiate_chat(
    researcher,
    message=(
        "Find a sentiment analysis API, use it to analyze these reviews: "
        "'Great product!', 'Terrible experience', 'Pretty good overall'. "
        "Then pass results to Analyst for a summary. End with TERMINATE."
    )
)
```

## Manual Registration (without `register_with_autogen`)

```python
import autogen
from autogen_x402_discovery import x402_discover

config_list = [{"model": "gpt-4o", "api_key": "YOUR_OPENAI_API_KEY"}]

assistant = autogen.AssistantAgent(
    name="assistant",
    llm_config={"config_list": config_list},
)

# Register manually with a custom description
assistant.register_for_llm(
    name="x402_discover",
    description=(
        "Find the best available x402-payable API endpoint for any capability. "
        "Returns endpoint URL, price per call, quality metrics, and Python code snippet."
    )
)(x402_discover)

user_proxy = autogen.UserProxyAgent(
    name="user_proxy",
    human_input_mode="NEVER",
    code_execution_config={"work_dir": "workspace", "use_docker": False},
)
user_proxy.register_for_execution(name="x402_discover")(x402_discover)
```

## Function Parameters

The `x402_discover` function accepts:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | required | Natural language description of the capability needed |
| `max_price_usd` | `float` | `0.50` | Maximum acceptable price per call in USD |

## Function Output

Returns a formatted string containing:

- **Service name** and **endpoint URL**
- **Price per call** in USD
- **Quality metrics**: uptime % and average latency (ms)
- **Description** of the service
- **Python code snippet** ready to execute

Example output:
```
Best match: NewsAPI Proxy
Endpoint: https://api.example.com/news
Price: $0.005/call
Quality: 98.5% uptime, 145ms avg
Description: Latest news headlines with full-text search
Code: import requests
resp = requests.get("https://api.example.com/news",
    headers={"X-Payment": "<x402-token>"},
    params={"q": "AI", "limit": 10})
print(resp.json())
```

## Calling Directly (Without an Agent)

```python
from autogen_x402_discovery import x402_discover

# Discover a data enrichment service
result = x402_discover(query="company data enrichment", max_price_usd=0.25)
print(result)

# Find a cheap OCR service
result = x402_discover(query="OCR optical character recognition", max_price_usd=0.10)
print(result)
```

## How It Works

1. AutoGen agent receives a task requiring an external API
2. Agent calls `x402_discover` with a description of the needed capability
3. The function fetches the [x402 discovery catalog](https://x402-discovery-api.onrender.com/catalog)
4. Services are filtered by `max_price_usd` and ranked by uptime/latency
5. The best match is returned with endpoint URL and a ready-to-run code snippet
6. Agent (or code executor) uses the snippet to call the service

## Discovery API

Browse all available services: [https://x402-discovery-api.onrender.com](https://x402-discovery-api.onrender.com)

- `GET /catalog` — List all registered x402 services with quality metrics
- `GET /discover?q=<query>` — Search by capability description
- `GET /health` — API health check

## Links

- [x402 Discovery API](https://x402-discovery-api.onrender.com)
- [GitHub](https://github.com/bazookam7/ouroboros)
- [PyPI](https://pypi.org/project/autogen-x402-discovery/)
- [Report an issue](https://github.com/bazookam7/ouroboros/issues)

## License

MIT
