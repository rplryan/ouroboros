#!/usr/bin/env python3
"""
Demonstrates: a LangChain research agent that discovers and calls x402-payable
research services at runtime, with no hardcoded endpoint URLs.

Pattern overview
----------------
1. The agent receives a research task.
2. ResearchTool queries the discovery layer to find the best available
   research service (capability="research", filtered by price and quality).
3. If a service is found, it calls the endpoint with an X-PAYMENT header
   (fake/demo value — replace with a real signed payment token from a funded
   Base wallet for production).
4. If no research service is found, the tool falls back gracefully.

The key insight: the agent never hardcodes a service URL. It discovers the
current best endpoint at runtime. If a better service is registered tomorrow,
the agent automatically finds it on its next run.

No x402discovery package required — uses requests directly.

Install for real LangChain usage:
    pip install langchain-openai langchain-core
"""

import time
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"
PAY_TO = "0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA"

# ---------------------------------------------------------------------------
# Discovery helper (raw requests, no SDK required)
# ---------------------------------------------------------------------------

def find_research_service(max_price: float = 0.20) -> dict | None:
    """Query the discovery catalog and return the best research service.

    Uses the free /catalog endpoint to avoid spending on discovery itself.
    Filters client-side: capability=research, price <= max_price.
    Ranks by quality tier (gold > silver > bronze > unverified).

    Returns the top-ranked service dict, or None if nothing matches.
    """
    try:
        resp = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15)
        resp.raise_for_status()
        services = resp.json().get("services", [])
    except requests.RequestException as e:
        print(f"[ResearchTool] Discovery failed: {e}")
        return None

    QUALITY_ORDER = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}

    candidates = [
        s for s in services
        if (
            "research" in s.get("capability_tags", [])
            or s.get("category") == "research"
        )
        and s.get("price_per_call", s.get("price_usd", 999)) <= max_price
    ]

    if not candidates:
        return None

    candidates.sort(
        key=lambda s: QUALITY_ORDER.get(s.get("quality_tier", "unverified"), 3)
    )
    return candidates[0]


# ---------------------------------------------------------------------------
# ResearchTool — drop-in LangChain BaseTool implementation
# ---------------------------------------------------------------------------

class ResearchTool:
    """A LangChain-compatible tool that discovers and calls x402 research services.

    In real LangChain usage, inherit from langchain_core.tools.BaseTool:

        from langchain_core.tools import BaseTool

        class ResearchTool(BaseTool):
            name = "x402_research"
            description = (
                "Search for information on any topic using a paid research API. "
                "Input: a research question as a string. "
                "Returns: a structured answer with sources."
            )

            def _run(self, query: str) -> str:
                return _call_research_service(query)

    The implementation below is self-contained for demo purposes.
    """

    name = "x402_research"
    description = (
        "Search for information on any topic using a paid research API. "
        "Input: a research question as a string. "
        "Returns: a structured answer with sources."
    )

    def run(self, query: str, max_price: float = 0.20) -> str:
        """Execute the research tool: discover + call."""
        print(f"[ResearchTool] Looking for research service (max ${max_price}/call)...")

        service = find_research_service(max_price=max_price)

        if service is None:
            return (
                "[ResearchTool] No research service currently available in the "
                "discovery index under the price threshold. "
                "Try again later or increase max_price."
            )

        endpoint = service.get("endpoint_url") or service.get("url")
        name = service.get("name", "unknown")
        price = service.get("price_per_call", service.get("price_usd", "?"))
        quality = service.get("quality_tier", "unverified")

        print(f"[ResearchTool] Found: {name}")
        print(f"               URL:     {endpoint}")
        print(f"               Price:   ${price}/call   Quality: {quality}")

        return _call_research_endpoint(endpoint, query, service)


def _call_research_endpoint(endpoint: str, query: str, service: dict) -> str:
    """Call the discovered research endpoint with a demo x402 payment header.

    In production, replace DEMO_PAYMENT_TOKEN with a real signed payment
    produced by your x402-capable HTTP client (e.g. coinbase/x402 SDK).

    The X-PAYMENT header value is a base64url-encoded JSON object containing:
      - payload: { from, to, network, asset, amount, resource, nonce, expiry }
      - signature: EIP-712 signature over the payload

    For demo purposes we send a clearly fake token; the service will reject
    it with 402, but the discovery + routing flow is fully exercised.
    """

    # Demo payment token — replace with real token from funded Base wallet
    DEMO_PAYMENT_TOKEN = (
        "eyJ4NDAyVmVyc2lvbiI6MiwiZGVtbyI6dHJ1ZSwi"
        "bm90ZSI6InJlcGxhY2Utd2l0aC1yZWFsLXRva2VuIn0="
    )

    headers = {
        "Content-Type": "application/json",
        "X-PAYMENT": DEMO_PAYMENT_TOKEN,
        "User-Agent": "x402-research-agent/1.0",
    }

    payload = {"query": query, "q": query}

    start = time.time()
    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        latency_ms = int((time.time() - start) * 1000)

        if resp.status_code == 402:
            # Expected with demo token — document the payment requirements
            payment_info = resp.json()
            accepts = payment_info.get("accepts", [{}])[0]
            amount_units = accepts.get("amount", "?")
            pay_to = accepts.get("payTo", PAY_TO)
            print(f"[ResearchTool] Payment required: {amount_units} USDC units -> {pay_to}")
            return (
                f"[ResearchTool] Service found but payment required. "
                f"Fund a Base wallet with USDC to execute. "
                f"Service: {service.get('name')} at ${service.get('price_per_call', '?')}/call. "
                f"Endpoint: {endpoint}"
            )

        elif resp.status_code == 200:
            _report_success(service.get("service_id", "unknown"), latency_ms)
            data = resp.json()
            return str(data.get("result") or data.get("answer") or data)

        else:
            print(f"[ResearchTool] Unexpected status {resp.status_code}: {resp.text[:200]}")
            _report_failure(service.get("service_id", "unknown"), latency_ms)
            return f"[ResearchTool] Service returned HTTP {resp.status_code}."

    except requests.Timeout:
        print("[ResearchTool] Request timed out.")
        return "[ResearchTool] Research service timed out. Try another service."

    except requests.RequestException as e:
        print(f"[ResearchTool] Request failed: {e}")
        return f"[ResearchTool] Could not reach research service: {e}"


def _report_success(service_id: str, latency_ms: int) -> None:
    """Best-effort report back to discovery layer."""
    try:
        requests.post(
            f"{DISCOVERY_URL}/report",
            json={"service_id": service_id, "called": True,
                  "result": "success", "latency_ms": latency_ms},
            timeout=5,
        )
    except Exception:
        pass


def _report_failure(service_id: str, latency_ms: int) -> None:
    """Best-effort failure report back to discovery layer."""
    try:
        requests.post(
            f"{DISCOVERY_URL}/report",
            json={"service_id": service_id, "called": True,
                  "result": "fail", "latency_ms": latency_ms},
            timeout=5,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LangChain agent wiring (shown as executable demo code)
# ---------------------------------------------------------------------------

LANGCHAIN_AGENT_CODE = '''
# Full LangChain agent — requires: pip install langchain-openai langchain-core

from langchain_openai import ChatOpenAI
from langchain_core.tools import BaseTool
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

class ResearchTool(BaseTool):
    name: str = "x402_research"
    description: str = (
        "Research any topic using a paid x402 API service. "
        "Input: research question as plain text. "
        "Returns: structured answer with cited sources."
    )

    def _run(self, query: str) -> str:
        import requests, time
        DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

        # Discover the best research service
        catalog = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15).json()
        candidates = [
            s for s in catalog.get("services", [])
            if "research" in s.get("capability_tags", [])
            or s.get("category") == "research"
        ]
        if not candidates:
            return "No research services found in discovery index."

        # Call with real x402 payment (requires funded wallet + x402 client)
        service = candidates[0]
        endpoint = service.get("endpoint_url") or service.get("url")
        resp = requests.post(endpoint, json={"query": query}, timeout=30)
        if resp.status_code == 402:
            return f"Payment required. Fund a Base USDC wallet. Service: {service['name']}"
        return str(resp.json())

# Wire up the agent
llm = ChatOpenAI(model="gpt-4o", temperature=0)
tools = [ResearchTool()]

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a research assistant. Use x402_research for factual queries."),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

agent = create_openai_functions_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

result = executor.invoke({
    "input": "What are the current EU AI Act compliance deadlines for foundation model providers?"
})
print(result["output"])
'''


# ---------------------------------------------------------------------------
# Demo — runs without LangChain or API keys
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("x402 LangChain Research Agent — Example 11")
    print("=" * 50)
    print()

    tool = ResearchTool()

    # Demonstrate the discovery + call flow
    query = "What are the key provisions of the EU AI Act for autonomous agents?"
    print(f"Query: {query}")
    print()

    result = tool.run(query, max_price=0.20)
    print()
    print("Result:")
    print(result)
    print()
    print("-" * 50)
    print("Full LangChain agent code (requires langchain-openai):")
    print(LANGCHAIN_AGENT_CODE)
