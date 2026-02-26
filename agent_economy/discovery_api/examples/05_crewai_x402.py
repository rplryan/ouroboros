#!/usr/bin/env python3
"""
Demonstrates: CrewAI crew with x402 service discovery tool.
Source: https://x402-discovery-api.onrender.com

Install: pip install crewai-x402-discovery crewai
"""
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

CREWAI_EXAMPLE = """
from crewai import Agent, Task, Crew
from x402discovery_crewai import X402DiscoveryTool

# Agent with x402 discovery capability
researcher = Agent(
    role="Research Specialist",
    goal="Find and orchestrate the best x402-payable services for research tasks",
    backstory="An autonomous agent expert in discovering and using paid API services",
    tools=[X402DiscoveryTool()],
    verbose=True,
)

# Task that requires service discovery
task = Task(
    description=(
        "Find the top 3 research services available under $0.20/call. "
        "Compare their quality tiers, latency, and uptime. "
        "Recommend the best one for a production AI pipeline."
    ),
    agent=researcher,
    expected_output="Ranked list of research services with recommendation",
)

crew = Crew(agents=[researcher], tasks=[task], verbose=True)
result = crew.kickoff()
print(result)
"""

print("CrewAI x402 Discovery Integration")
print("=" * 40)
print("Install: pip install crewai-x402-discovery crewai")
print(CREWAI_EXAMPLE)

# Live demo without CrewAI installed
resp = requests.get(f"{DISCOVERY_URL}/catalog")
services = resp.json().get("services", [])
research_svcs = [s for s in services if "research" in s.get("capability_tags", []) or s.get("category") == "research"]
print(f"Live check: {len(research_svcs)} research services available")
for s in research_svcs[:3]:
    print(f"  - {s['name']} [{s.get('quality_tier', 'unverified')}] ${s.get('price_per_call','?')}/call")
