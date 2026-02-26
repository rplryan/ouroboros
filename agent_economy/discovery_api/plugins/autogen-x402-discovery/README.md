# autogen-x402-discovery

AutoGen tool for **x402 service discovery** — let your AutoGen agents find and call any paid API endpoint at runtime.

When your AutoGen agent needs web search, image generation, data enrichment, or any other external capability, it calls `x402_discover` to find the best available service from the live [x402 discovery catalog](https://x402-discovery-api.onrender.com/catalog).

## Installation

```bash
pip install autogen-x402-discovery
```

## Quick Start

```python
import autogen
from autogen_x402_discovery import register_with_autogen

config_list = [{"model": "gpt-4o", "api_key": "your-key"}]

assistant = autogen.ConversableAgent(
    "assistant",
    llm_config={"config_list": config_list},
    system_message="Use x402_discover to find paid API services when needed.",
)

# Register the discovery tool
register_with_autogen(assistant)

user_proxy = autogen.UserProxyAgent("user", human_input_mode="NEVER")
user_proxy.initiate_chat(assistant, message="Find a crypto price API under $0.01/call")
```

## OpenAI Function Calling Schema

```python
from autogen_x402_discovery import get_autogen_tool_schema, x402_discover

# Get the schema for use with any OpenAI-compatible API
schema = get_autogen_tool_schema()

# Call the function directly
result = x402_discover("web search", max_price_usd=0.10)
print(result)
```

## Tool Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | required | Natural language description of the capability needed |
| `max_price_usd` | `float` | `0.50` | Maximum acceptable price per call in USD |

## How It Works

1. Agent calls `x402_discover("web search")`
2. Tool fetches the [free catalog](https://x402-discovery-api.onrender.com/catalog)
3. Services are filtered by `max_price_usd` and matched by keyword
4. Results are ranked by uptime % and latency
5. Returns endpoint URL, price, and a Python snippet

## Links

- [x402 Discovery API](https://x402-discovery-api.onrender.com)
- [GitHub](https://github.com/bazookam7/ouroboros)

## License

MIT
