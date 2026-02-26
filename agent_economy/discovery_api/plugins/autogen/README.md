# autogen-x402-discovery

AutoGen function tool for discovering x402-payable services at runtime.

## Install

```bash
pip install autogen-x402-discovery
```

## Usage

```python
import autogen
from x402discovery_autogen import x402_discover_function, X402_DISCOVERY_TOOL_SCHEMA

# Register as a function tool
config = autogen.AssistantAgent(
    name="x402_researcher",
    llm_config={
        "functions": [X402_DISCOVERY_TOOL_SCHEMA],
        "config_list": [{"model": "gpt-4o", "api_key": "..."}],
    },
)

user = autogen.UserProxyAgent(
    name="user",
    function_map={"x402_discover": x402_discover_function},
)

user.initiate_chat(
    config,
    message="Find the best research service under $0.10/call"
)
```

Powered by the [x402 Service Discovery API](https://x402-discovery-api.onrender.com).
