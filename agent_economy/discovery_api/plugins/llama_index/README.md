# llama-index-x402-discovery

A LlamaIndex `FunctionTool` that lets any LlamaIndex agent or query engine discover x402-payable API services at runtime via the [x402 Service Discovery API](https://x402-discovery-api.onrender.com). Returns quality-ranked results so your agent can find the best available endpoint without hardcoded URLs.

## Install

```bash
pip install llama-index-x402-discovery
# or without PyPI:
pip install requests llama-index-core
# and copy x402discovery_llama/__init__.py into your project
```

## Usage

```python
from x402discovery_llama import X402DiscoveryTool
from llama_index.core.agent import ReActAgent
from llama_index.llms.openai import OpenAI

llm = OpenAI(model="gpt-4o-mini")
agent = ReActAgent.from_tools([X402DiscoveryTool], llm=llm, verbose=True)
response = agent.chat("Find a data enrichment service under $0.05 per call")
print(response)
```

The agent calls `x402_discover` and returns up to 5 quality-ranked services with endpoint URLs and pricing so it can choose the best one.
