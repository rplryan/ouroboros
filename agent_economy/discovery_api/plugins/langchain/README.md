# langchain-x402-discovery

A LangChain `BaseTool` that lets any LangChain agent discover x402-payable API services at runtime via the [x402 Service Discovery API](https://x402-discovery-api.onrender.com). Instead of hardcoding service URLs, your agent queries the discovery catalog and finds the best available endpoint ranked by quality tier and price.

## Install

```bash
pip install langchain-x402-discovery
# or without PyPI:
pip install requests langchain-core
# and copy x402discovery_langchain/__init__.py into your project
```

## Usage

```python
from x402discovery_langchain import X402DiscoveryTool
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini")
agent = initialize_agent(
    tools=[X402DiscoveryTool()],
    llm=llm,
    agent=AgentType.OPENAI_FUNCTIONS,
    verbose=True,
)
result = agent.run("Find a web research API under $0.10 per call")
print(result)
```

The agent will call `x402_discover(capability="research", max_price_usd=0.10)` and return quality-ranked results with endpoint URLs and pricing.
