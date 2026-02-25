# crewai-x402-discovery

CrewAI tool for **x402 service discovery** — let your CrewAI agents find and call any paid API endpoint at runtime without hardcoding URLs or API keys.

Add `X402DiscoveryTool` to any CrewAI agent and it can autonomously locate web search, data enrichment, image analysis, or any external service from the live [x402 discovery catalog](https://x402-discovery-api.onrender.com).

## Installation

```bash
pip install crewai-x402-discovery
```

## Quick Start

```python
from crewai import Agent, Task, Crew
from crewai_x402_discovery import X402DiscoveryTool

# Create the discovery tool
x402_tool = X402DiscoveryTool()

# Assign it to an agent
researcher = Agent(
    role="API Research Specialist",
    goal="Find and evaluate the best available x402-payable API services",
    backstory="You specialize in discovering and assessing paid API services for agent use.",
    tools=[x402_tool],
    verbose=True
)

task = Task(
    description="Find the best web search API available for under $0.05 per call. Report its URL, price, and uptime.",
    agent=researcher,
    expected_output="API endpoint URL, price per call, uptime percentage, and a brief description"
)

crew = Crew(agents=[researcher], tasks=[task])
result = crew.kickoff()
print(result)
```

## Full Working Example — Multi-Agent Research Crew

```python
from crewai import Agent, Task, Crew, Process
from crewai_x402_discovery import X402DiscoveryTool

# Discovery tool with a custom price ceiling
x402_tool = X402DiscoveryTool(max_price_usd=0.10)

# Agent 1: Discovers the right API service
api_finder = Agent(
    role="API Discovery Agent",
    goal="Find the most reliable and cost-effective x402 API services for any given task",
    backstory=(
        "You are an expert at finding the right API for any job. "
        "You always check the x402 catalog first before recommending a service. "
        "You prioritize services with high uptime and low latency."
    ),
    tools=[x402_tool],
    verbose=True,
    allow_delegation=False
)

# Agent 2: Uses the discovered service
data_analyst = Agent(
    role="Data Analyst",
    goal="Use discovered APIs to gather and analyze data, then produce clear reports",
    backstory="You execute API calls and transform raw data into actionable insights.",
    verbose=True,
    allow_delegation=False
)

# Task 1: Find the API
discovery_task = Task(
    description=(
        "Use x402_service_discovery to find the best sentiment analysis API "
        "that costs less than $0.10/call. Return the endpoint URL, price, and "
        "the Python code snippet for calling it."
    ),
    agent=api_finder,
    expected_output="Endpoint URL, price per call, and Python code snippet"
)

# Task 2: Use the API
analysis_task = Task(
    description=(
        "Using the API endpoint discovered in the previous task, analyze the sentiment "
        "of these three reviews:\n"
        "1. 'This product exceeded all my expectations!'\n"
        "2. 'Worst purchase I have ever made.'\n"
        "3. 'It is okay, nothing special.'\n"
        "Report positive/negative/neutral for each."
    ),
    agent=data_analyst,
    expected_output="Sentiment classification for each of the three reviews",
    context=[discovery_task]
)

crew = Crew(
    agents=[api_finder, data_analyst],
    tasks=[discovery_task, analysis_task],
    process=Process.sequential,
    verbose=True
)

result = crew.kickoff()
print(result)
```

## Tool Configuration

```python
from crewai_x402_discovery import X402DiscoveryTool

# Default configuration
tool = X402DiscoveryTool()

# Custom price ceiling (only show services under $0.02/call)
tool = X402DiscoveryTool(max_price_usd=0.02)

# Custom discovery API URL (e.g. a private or self-hosted catalog)
tool = X402DiscoveryTool(
    discovery_api_url="https://x402-discovery-api.onrender.com",
    max_price_usd=0.25
)
```

## Tool Properties

| Property | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | `"x402_service_discovery"` | Tool name (used by the LLM) |
| `description` | `str` | auto | Shown to the LLM to decide when to use this tool |
| `discovery_api_url` | `str` | `"https://x402-discovery-api.onrender.com"` | Discovery API base URL |
| `max_price_usd` | `float` | `0.50` | Maximum price per call in USD |

## Tool Input

The tool accepts a single `query` string: a natural language description of what capability you need.

Examples:
- `"web search"`
- `"image generation under 512x512"`
- `"company email verification"`
- `"real-time stock prices"`
- `"PDF text extraction"`

## Tool Output

Returns a formatted string containing:

- **Service name** and **endpoint URL**
- **Cost per call** in USD
- **Uptime %**
- **Description** of the service
- **Python code snippet** showing exactly how to call the endpoint

Example output:
```
Found: StockData Live
URL: https://api.example.com/stocks
Cost: $0.003/call
Uptime: 99.8%
Description: Real-time stock quotes and historical OHLCV data
Usage:
import requests
resp = requests.get("https://api.example.com/stocks",
    headers={"X-Payment": "<x402-token>"},
    params={"symbol": "AAPL"})
print(resp.json())
```

## How It Works

1. CrewAI agent receives a task requiring an external data source or API
2. Agent calls `x402_service_discovery` with a description of what it needs
3. The tool fetches the [x402 discovery catalog](https://x402-discovery-api.onrender.com/catalog)
4. Services are filtered by `max_price_usd` and ranked by uptime/latency
5. The best match is returned with endpoint URL and a ready-to-use code snippet
6. Agent uses the snippet to call the service and complete the task

## Discovery API

Browse all available services: [https://x402-discovery-api.onrender.com](https://x402-discovery-api.onrender.com)

- `GET /catalog` — List all registered x402 services with quality metrics
- `GET /discover?q=<query>` — Search by capability description
- `GET /health` — API health check

## Links

- [x402 Discovery API](https://x402-discovery-api.onrender.com)
- [GitHub](https://github.com/bazookam7/ouroboros)
- [PyPI](https://pypi.org/project/crewai-x402-discovery/)
- [Report an issue](https://github.com/bazookam7/ouroboros/issues)

## License

MIT
