# x402 Service Discovery — Stack Overflow Q&A Reference

Five self-contained question-and-answer pairs covering x402 service discovery.
Each answer is complete and copy-pasteable. All code uses `requests` directly.

Discovery API: https://x402-discovery-api.onrender.com

---

## Q1: How do I find x402-payable APIs for my autonomous agent?

**Tags:** `x402` `autonomous-agents` `api-discovery` `python`

**Question:**

I'm building an autonomous agent in Python and want it to be able to call
paid API services using the x402 micropayment protocol. I don't want to
hardcode specific service URLs — I want the agent to discover them at
runtime. Is there a directory or API for this?

**Answer:**

Yes — there's a service discovery layer specifically for x402-payable APIs at
`https://x402-discovery-api.onrender.com`. The free `/catalog` endpoint
returns all indexed services as JSON.

```python
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

# Get all indexed services (free, no payment required)
resp = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15)
services = resp.json().get("services", [])

print(f"{len(services)} services indexed")
for svc in services:
    print(f"  {svc['name']:30}  ${svc.get('price_per_call', svc.get('price_usd', '?'))}/call  "
          f"{svc.get('quality_tier', 'unverified')}")
```

To filter by what the service does, use the `capability_tags` or `category`
field:

```python
research_services = [
    s for s in services
    if "research" in s.get("capability_tags", [])
    or s.get("category") == "research"
]
```

There's also a paid search endpoint (`/discover`) that does server-side
filtering and quality ranking, but the free catalog is sufficient for most
use cases if you filter client-side.

Each service entry includes:
- `endpoint_url` — the URL to call with x402 payment
- `price_per_call` — cost in USD
- `quality_tier` — `unverified`, `bronze`, `silver`, or `gold` (based on
  monitored uptime and latency)
- `llm_usage_prompt` — a pre-written instruction you can inject into an LLM's
  context to teach it how to call the service

The well-known endpoint `/.well-known/x402-discovery` returns the same data
in a standardized format suitable for automated crawlers:

```python
resp = requests.get(f"{DISCOVERY_URL}/.well-known/x402-discovery")
index = resp.json()
print(f"Schema version: {index.get('x402_discovery_version')}")
print(f"Services: {index.get('total_services')}")
```

---

## Q2: How do I integrate x402 micropayments into a LangChain agent?

**Tags:** `langchain` `x402` `micropayments` `python` `autonomous-agents`

**Question:**

I have a LangChain agent and I want to give it access to paid x402 API
services. How do I create a LangChain tool that discovers and calls x402
endpoints? I don't have a specific service URL in mind — the agent should
pick the best available service at runtime.

**Answer:**

Create a `BaseTool` that wraps the discovery layer. The tool discovers the
best available endpoint for a capability and attempts to call it. With a
funded Base wallet + the `x402` Python client, the payment happens
automatically inside the request. Without a wallet, the service returns
HTTP 402 with payment instructions.

```python
import requests
import time
from langchain_core.tools import BaseTool

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

QUALITY_ORDER = {"gold": 0, "silver": 1, "bronze": 2, "unverified": 3}


def find_best_service(capability: str, max_price: float = 0.50) -> dict | None:
    """Discover the highest-quality service under the price ceiling."""
    resp = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15)
    services = resp.json().get("services", [])

    candidates = [
        s for s in services
        if (capability in s.get("capability_tags", [])
            or s.get("category") == capability)
        and s.get("price_per_call", s.get("price_usd", 999)) <= max_price
    ]

    candidates.sort(key=lambda s: QUALITY_ORDER.get(s.get("quality_tier", "unverified"), 3))
    return candidates[0] if candidates else None


class X402ResearchTool(BaseTool):
    name: str = "x402_research"
    description: str = (
        "Research any topic using a paid x402 API. "
        "Input: a research question as a string. "
        "Returns: a structured answer."
    )

    def _run(self, query: str) -> str:
        service = find_best_service("research", max_price=0.20)
        if not service:
            return "No research services currently available."

        endpoint = service.get("endpoint_url") or service.get("url")

        # With a funded wallet, use the x402 Python client:
        #   from x402.client import wrap
        #   resp = wrap(requests).post(endpoint, json={"query": query})
        # Without a wallet, this demonstrates the discovery + routing flow:
        resp = requests.post(
            endpoint,
            json={"query": query},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        if resp.status_code == 402:
            info = resp.json().get("accepts", [{}])[0]
            return (f"Payment required: {info.get('amount')} USDC units to "
                    f"{info.get('payTo')}. Fund a Base wallet to execute.")

        if resp.status_code == 200:
            return str(resp.json())

        return f"Service returned HTTP {resp.status_code}"


# Wire up the LangChain agent
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

llm = ChatOpenAI(model="gpt-4o", temperature=0)
tools = [X402ResearchTool()]

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a research assistant. Use x402_research for factual queries."),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

agent = create_openai_functions_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

result = executor.invoke({"input": "What is the current EU AI Act status?"})
print(result["output"])
```

The key point: the tool discovers the service URL at call time, so the agent
automatically uses the best available endpoint without any code changes.

---

## Q3: What is the x402 protocol and how do agents pay for APIs?

**Tags:** `x402` `http-402` `micropayments` `blockchain` `base-network`

**Question:**

I keep seeing references to "x402" and "HTTP 402 payments" in the context
of autonomous agents. What is this protocol and how does it work mechanically?
How does an agent actually pay for an API call?

**Answer:**

The x402 protocol is a standard for HTTP micropayments using the HTTP 402
("Payment Required") status code. It lets APIs charge per-call without
accounts, subscriptions, or OAuth — the payment header is the entire
credential.

**How it works:**

1. The agent makes a regular HTTP request to an API endpoint (e.g. `GET /research?q=...`).
2. The server responds with HTTP 402 and a JSON body describing payment requirements:

```json
{
  "error": "Payment Required",
  "x402Version": 2,
  "accepts": [{
    "scheme": "exact",
    "network": "eip155:8453",
    "amount": "50000",
    "resource": "https://api.example.com/research",
    "description": "Research API query",
    "payTo": "0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA",
    "maxTimeoutSeconds": 60,
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
  }]
}
```

3. The agent constructs a signed payment: a USDC transfer on Base (Ethereum L2)
   from its wallet to the `payTo` address, for the specified `amount` in token
   units (50000 = $0.05 with 6 decimals).
4. The signed payment is encoded as a base64url string and sent as the
   `X-PAYMENT` header on a repeat request.
5. The server verifies the payment via `https://x402.org/facilitator/verify`
   and, if valid, returns HTTP 200 with the result.

**In Python, using the x402 client:**

```python
import requests
from x402.client import wrap  # pip install x402

# wrap() intercepts 402 responses and handles payment automatically
# Requires a funded Base wallet configured in your environment
paid_requests = wrap(requests)

resp = paid_requests.get(
    "https://api.example.com/research",
    params={"q": "What is the x402 protocol?"}
)
print(resp.json())
```

**Without the x402 client (manual demo):**

```python
import requests

# First request — expect 402
resp = requests.get("https://api.example.com/research", params={"q": "test"})
assert resp.status_code == 402

payment_info = resp.json()
print("Network:", payment_info["accepts"][0]["network"])   # eip155:8453 = Base
print("Amount:", payment_info["accepts"][0]["amount"])     # in USDC token units
print("Pay to:", payment_info["accepts"][0]["payTo"])

# Construct and sign payment (requires wallet + EIP-712 signing logic)
# Then retry with header:
# resp2 = requests.get(..., headers={"X-PAYMENT": "<signed_token>"})
```

**Key properties:**
- No API keys, no accounts, no OAuth
- Payment is atomic: if verification fails, the server never processes the request
- Payments expire (typically 60 seconds) to prevent replay attacks
- Works with any Base-compatible wallet
- Any autonomous agent with a funded wallet can pay any x402 API

---

## Q4: How can I check the quality and uptime of x402 endpoints before calling them?

**Tags:** `x402` `api-monitoring` `uptime` `quality` `python`

**Question:**

Before my agent calls an x402 service, I want to verify it's actually up and
check its historical reliability. Is there a way to query uptime and latency
data for x402 endpoints without calling them directly?

**Answer:**

The x402 discovery layer provides two free endpoints for this:

- `/health/{service_id}` — live health check (makes a real request now)
- `/catalog` — includes `quality_tier`, `uptime_pct`, and `avg_latency_ms`
  for all indexed services

**Check a specific service:**

```python
import requests

DISCOVERY_URL = "https://x402-discovery-api.onrender.com"

def check_service_health(service_id: str) -> dict:
    """Get live health status for a service."""
    resp = requests.get(f"{DISCOVERY_URL}/health/{service_id}", timeout=10)
    if resp.status_code == 404:
        return {"error": f"Service {service_id!r} not found"}
    resp.raise_for_status()
    return resp.json()

# Example: check a specific service
health = check_service_health("ouroboros/deep-research")
print(f"Status:    {health.get('status')}")
print(f"Uptime 7d: {health.get('uptime_pct')}%")
print(f"Latency:   {health.get('latency_ms')}ms")
print(f"Tier:      {health.get('quality_tier')}")
```

**Filter the catalog by minimum quality before calling:**

```python
def get_reliable_services(capability: str, min_uptime: float = 95.0) -> list[dict]:
    """Return services for a capability with uptime above threshold."""
    resp = requests.get(f"{DISCOVERY_URL}/catalog", timeout=15)
    services = resp.json().get("services", [])

    return [
        s for s in services
        if (capability in s.get("capability_tags", [])
            or s.get("category") == capability)
        and (s.get("uptime_pct") or 0) >= min_uptime
    ]

reliable = get_reliable_services("research", min_uptime=95.0)
print(f"Research services with >95% uptime: {len(reliable)}")
for s in reliable:
    print(f"  {s['name']:30} uptime={s.get('uptime_pct')}%  "
          f"latency={s.get('avg_latency_ms')}ms  tier={s.get('quality_tier')}")
```

**Quality tiers** are assigned automatically by the discovery layer based on
monitored data (not self-reported):

| Tier       | Uptime (7d) | p95 Latency | Monitoring |
|------------|-------------|-------------|------------|
| gold       | ≥ 99%       | < 500ms     | ≥ 30 days  |
| silver     | ≥ 95%       | < 1000ms    | ≥ 7 days   |
| bronze     | ≥ 80%       | < 2000ms    | any        |
| unverified | < 10 checks | —           | < 10 checks|

For mission-critical tasks, filter with `min_quality="silver"` or `"gold"`.
For best-effort or cheap operations, `"bronze"` or `"unverified"` may be
acceptable.

**Report your own observations** (optional, improves quality scores for
future agents):

```python
# After calling a service, report the outcome
requests.post(
    f"{DISCOVERY_URL}/report",
    json={
        "service_id": "ouroboros/deep-research",
        "called": True,
        "result": "success",  # or "fail" / "timeout"
        "latency_ms": 342,
    },
    timeout=5,
)
```

---

## Q5: How do I create a service that charges for API access via x402?

**Tags:** `x402` `fastapi` `python` `micropayments` `api-monetization`

**Question:**

I've built a Python API and I want to charge per call using x402 micropayments.
How do I implement the x402 payment gate, and how do I register the service
so autonomous agents can discover it?

**Answer:**

There are two steps: implement the x402 payment gate in your API, then register
with the discovery layer so agents can find you.

**Step 1: Implement the x402 gate (FastAPI example)**

```python
from fastapi import FastAPI, Request, Response
import httpx
import os

app = FastAPI()

PAYMENT_AMOUNT = "50000"          # 0.05 USDC (6 decimal places)
PAY_TO = "0xDBBe14C418466Bf5BF0ED7638B4E6849B852aFfA"  # your wallet
USDC_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # USDC on Base
FACILITATOR = "https://x402.org/facilitator/verify"

PAYMENT_REQUIRED = {
    "error": "Payment Required",
    "x402Version": 2,
    "accepts": [{
        "scheme": "exact",
        "network": "eip155:8453",
        "amount": PAYMENT_AMOUNT,
        "resource": "https://your-api.example.com/research",
        "description": "Research API query — 0.05 USDC per call",
        "mimeType": "application/json",
        "payTo": PAY_TO,
        "maxTimeoutSeconds": 60,
        "asset": USDC_CONTRACT,
        "extra": {"name": "USDC", "version": "2"},
    }],
}


async def verify_payment(token: str, resource: str) -> bool:
    """Verify a payment token with the x402 facilitator."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            FACILITATOR,
            json={"x402Version": 2, "payload": token, "resource": resource},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("isValid", False)
    return False


@app.get("/research")
async def research(request: Request, q: str = ""):
    payment_token = request.headers.get("X-PAYMENT")

    if not payment_token:
        return Response(
            content=__import__("json").dumps(PAYMENT_REQUIRED),
            status_code=402,
            media_type="application/json",
        )

    resource = str(request.url)
    if not await verify_payment(payment_token, resource):
        return Response(
            content='{"error": "Invalid payment"}',
            status_code=402,
            media_type="application/json",
        )

    # Payment verified — execute the request
    answer = await do_research(q)
    return {"result": answer, "query": q}


async def do_research(query: str) -> str:
    # Your actual implementation here
    return f"Research result for: {query}"
```

**Step 2: Expose /.well-known/x402-discovery**

```python
@app.get("/.well-known/x402-discovery")
async def well_known():
    return {
        "x402_discovery_version": "0.1",
        "services": [{
            "service_id": "your-org/research-api",
            "name": "Your Research API",
            "description": "Takes a research question. Returns a structured answer with sources.",
            "capability_tags": ["research", "summarization"],
            "endpoint_url": "https://your-api.example.com/research",
            "network": "base",
            "payment_token": "usdc",
            "price_per_call": 0.05,
            "pricing_model": "flat",
            "provider_wallet": PAY_TO,
            "agent_callable": True,
            "input_format": "natural_language",
            "output_format": "json",
            "auth_required": False,
        }]
    }
```

**Step 3: Register with the discovery layer**

```python
import requests

requests.post(
    "https://x402-discovery-api.onrender.com/register",
    json={
        "name": "Your Research API",
        "url": "https://your-api.example.com/research",
        "description": "Takes a research question. Returns a structured answer.",
        "price_usd": 0.05,
        "category": "research",
    },
    timeout=15,
)
```

Once registered, the discovery layer health-checks your endpoint every 5 minutes.
After 10+ checks with good uptime, it will assign a quality tier (bronze, silver,
or gold). Autonomous agents querying the discovery index will find your service
automatically.
