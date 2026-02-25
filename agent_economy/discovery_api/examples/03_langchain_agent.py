#!/usr/bin/env python3
"""
Demonstrates: LangChain agent using x402 service discovery as a tool.
Source: https://x402-discovery-api.onrender.com

Install: pip install langchain-openai langchain-x402-discovery
"""
import os
# from langchain.agents import initialize_agent, AgentType
# from langchain_openai import ChatOpenAI
# from x402discovery_langchain import X402DiscoveryTool

# For demo purposes, we show what the agent integration looks like
# without requiring API keys to run this file.

DEMO_CODE = """
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI
from x402discovery_langchain import X402DiscoveryTool

# Set up the LLM
llm = ChatOpenAI(model="gpt-4o", temperature=0)

# Add x402 discovery as a tool
tools = [X402DiscoveryTool()]

# Initialize a function-calling agent
agent = initialize_agent(
    tools,
    llm,
    agent=AgentType.OPENAI_FUNCTIONS,
    verbose=True,
)

# The agent will automatically call x402_discover when it needs paid services
result = agent.run(
    "I need to research current EU AI Act compliance requirements. "
    "Find the best available research service under $0.20/call."
)
print(result)
"""

print("LangChain x402 Discovery Integration")
print("=" * 40)
print("Install: pip install langchain-x402-discovery langchain-openai")
print()
print("Example code:")
print(DEMO_CODE)

# Direct usage without LangChain (no API key needed)
import requests
resp = requests.get("https://x402-discovery-api.onrender.com/catalog")
services = resp.json().get("services", [])
print(f"\nDirect API check: {len(services)} services currently indexed")
if services:
    print(f"Example service: {services[0]['name']} at ${services[0].get('price_per_call', '?')}/call")
