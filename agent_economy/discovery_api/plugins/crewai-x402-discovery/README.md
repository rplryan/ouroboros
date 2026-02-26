# crewai-x402-discovery

CrewAI tool for **x402 service discovery** — let your CrewAI agents find and call any paid API endpoint at runtime.

## Installation

```bash
pip install crewai-x402-discovery
```

## Quick Start

```python
from crewai import Agent, Task, Crew
from crewai_x402_discovery import X402DiscoveryTool

tool = X402DiscoveryTool()

researcher = Agent(
    role="Research Specialist",
    goal="Find and use the best available APIs for any research task",
    backstory="An expert at finding and using external APIs efficiently.",
    tools=[tool],
    verbose=True,
)

task = Task(
    description="Find the best web search API available under $0.02/call and report its details.",
    expected_output="API name, URL, price, and a Python usage snippet.",
    agent=researcher,
)

crew = Crew(agents=[researcher], tasks=[task], verbose=True)
result = crew.kickoff()
print(result)
```

## Configuration

```python
from crewai_x402_discovery import X402DiscoveryTool

# Custom price limit
tool = X402DiscoveryTool(max_price_usd=0.10)

# Custom discovery API (e.g. private catalog)
tool = X402DiscoveryTool(
    discovery_api_url="https://x402-discovery-api.onrender.com",
    max_price_usd=0.50,
)
```

## Tool Parameters

The tool accepts a natural language query string. Examples:
- `"web search"`
- `"image generation"`
- `"crypto prices"`
- `"data enrichment"`
- `"regulatory filings"`

## Links

- [x402 Discovery API](https://x402-discovery-api.onrender.com)
- [GitHub](https://github.com/bazookam7/ouroboros)

## License

MIT
