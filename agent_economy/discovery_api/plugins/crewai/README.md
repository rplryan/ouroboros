# crewai-x402-discovery

CrewAI tool for discovering x402-payable services at runtime.

## Install

```bash
pip install crewai-x402-discovery
```

## Usage

```python
from crewai import Agent, Task, Crew
from x402discovery_crewai import X402DiscoveryTool

researcher = Agent(
    role="Research Specialist",
    goal="Find and delegate tasks to specialized x402-payable services",
    backstory="Expert at discovering and orchestrating paid AI services",
    tools=[X402DiscoveryTool()],
    verbose=True,
)

task = Task(
    description="Find the best research service for AI regulation topics, under $0.20/call",
    agent=researcher,
)

crew = Crew(agents=[researcher], tasks=[task])
result = crew.kickoff()
print(result)
```

Powered by the [x402 Service Discovery API](https://x402-discovery-api.onrender.com).
