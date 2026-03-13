"""
Content library for x402Scout social media.
All X posts are ≤280 chars. Discord posts can be longer.
Organized by content pillar from scout_social_strategy.

@mentions strategy:
  @base — any Base ecosystem / on-chain content
  @coinbase — CDP / protocol-level content
  @stripe — Stripe x402 news specifically
Hashtag strategy (1-2 max):
  #x402 — ecosystem posts
  #buildinpublic — build-in-public posts
Hot takes: bare (no tags) — they perform better raw
"""

# Each entry: {id, pillar, platform, content, tags, priority}
# platform: "x", "discord_cdp", "discord_base", "all"
# priority: 1=high, 2=medium, 3=low

CONTENT_LIBRARY = [
    # ─────────────────────────────────────────────────────────
    # PILLAR 1: BUILD IN PUBLIC (Revenue & Metrics)
    # ─────────────────────────────────────────────────────────
    {
        "id": "bip_001",
        "pillar": "build_in_public",
        "platform": "x",
        "content": "x402Scout just crossed 803 registered services.\n\nA week ago: ~534.\nToday: 803+.\n\nThat's +269 services in 7 days. Auto-discovery running every 6h. No approval gate.\n\nx402scout.com\n\n@base #buildinpublic",
        "tags": ["milestone", "growth"],
        "priority": 1,
    },
    {
        "id": "bip_002",
        "pillar": "build_in_public",
        "platform": "x",
        "content": "ScoutGate: day 1 numbers.\n\nReal on-chain settlement: ✅\n1 API registered in first 30 min: ✅\nPayment verified on Base mainnet: ✅\n\nThe infrastructure is boring. That's the point.\n\nhttps://x402-scoutgate.onrender.com\n\n@base",
        "tags": ["scoutgate", "launch"],
        "priority": 1,
    },
    {
        "id": "bip_003",
        "pillar": "build_in_public",
        "platform": "x",
        "content": "Honest pricing history for ScoutGate:\n\n0.5% → 1% → 2.5% → 2%\n\nAll in one day. The right number was in my first recommendation. Lesson: anchor on your own analysis, not the last suggestion you heard.",
        "tags": ["pricing", "lessons"],
        "priority": 2,
    },
    {
        "id": "bip_004",
        "pillar": "build_in_public",
        "platform": "x",
        "content": "x402Scout infrastructure costs:\n\n• Render free tier: $0/mo\n• Domain (x402scout.com): $12/yr\n• Persistent disk (1GB): $0.25/mo\n\nTotal: ~$3/mo\nRevenue: USDC per API call\n\nThis is what lean looks like.\n\n@base",
        "tags": ["costs", "transparency"],
        "priority": 2,
    },
    {
        "id": "bip_005",
        "pillar": "build_in_public",
        "platform": "x",
        "content": "Building x402 infrastructure in public.\n\nWeek 4 snapshot:\n• Discovery API: 1,072 services\n• ScoutGate: live, 2% fee, on-chain verified\n• RouteNet: routing on Base\n• scout_relay: MCP-native relay\n\nAll solo. All live. No raises.\n\n@base #buildinpublic",
        "tags": ["week_in_review", "transparency"],
        "priority": 1,
    },

    # ─────────────────────────────────────────────────────────
    # PILLAR 2: ECOSYSTEM INTEL (Maps, Gaps, Data)
    # ─────────────────────────────────────────────────────────
    {
        "id": "eco_001",
        "pillar": "ecosystem_intel",
        "platform": "x",
        "content": "1,072 x402 services indexed.\n\nBiggest categories:\n• AI/ML inference APIs: ~31%\n• Data feeds: ~22%\n• Dev tools: ~18%\n• MCP servers: ~14%\n• Finance: ~9%\n\nThe agent economy is mostly AI eating AI.\n\nFull catalog: x402scout.com\n\n#x402",
        "tags": ["data", "ecosystem"],
        "priority": 1,
    },
    {
        "id": "eco_002",
        "pillar": "ecosystem_intel",
        "platform": "x",
        "content": "The x402 ecosystem gap nobody's talking about:\n\nThere's no pricing intelligence.\n\nDevelopers setting per-call prices are guessing. No benchmark. No data. No \"what does the market charge for image classification?\"\n\nThat's x402 Intel — building it next.\n\n#x402",
        "tags": ["gap_analysis", "intel"],
        "priority": 1,
    },
    {
        "id": "eco_003",
        "pillar": "ecosystem_intel",
        "platform": "x",
        "content": "x402 ecosystem composition:\n\n23+ facilitators. Hundreds of services. But only ~12 have >100 real users.\n\nLagging indicator: most projects announce first, ship... eventually.\n\nLeading indicator: clone traffic, catalog registrations, actual payments.\n\n#x402",
        "tags": ["ecosystem", "analysis"],
        "priority": 2,
    },
    {
        "id": "eco_004",
        "pillar": "ecosystem_intel",
        "platform": "x",
        "content": "What 1,072 x402 services taught me about pricing:\n\n• Median per-call: $0.001–$0.005\n• Premium compute: $0.10–$0.50\n• Sweet spot for new services: $0.002\n• \"I'll figure it out later\" == $0 forever\n\nSet a price. Any price. You can change it.\n\n#x402",
        "tags": ["pricing", "data"],
        "priority": 1,
    },
    {
        "id": "eco_005",
        "pillar": "ecosystem_intel",
        "platform": "x",
        "content": "Ecosystem map: who owns what in x402\n\n• Protocol: @coinbase + Cloudflare\n• Facilitator: Coinbase (dominant, free)\n• Discovery: x402Scout (us)\n• Routing: RouteNet (us) on @base\n• Monetization gateway: ScoutGate (us)\n• Intelligence: nobody yet\n\nThe stack is forming.",
        "tags": ["ecosystem_map", "competitive"],
        "priority": 2,
    },

    # ─────────────────────────────────────────────────────────
    # PILLAR 3: TUTORIALS (How to build with Scout)
    # ─────────────────────────────────────────────────────────
    {
        "id": "tut_001",
        "pillar": "tutorials",
        "platform": "x",
        "content": "Monetize your API with x402 in 30 seconds:\n\n```\ncurl -X POST https://x402-scoutgate.onrender.com/register \\\n  -d '{\"api_url\":\"https://your-api.com\",\"wallet_address\":\"0x...\",\"price_usd\":0.005}'\n```\n\nProxy URL returned. Charges per call.\n\n@base #x402",
        "tags": ["tutorial", "scoutgate"],
        "priority": 1,
    },
    {
        "id": "tut_002",
        "pillar": "tutorials",
        "platform": "x",
        "content": "How to find x402 services for your AI agent:\n\nOption A: `curl https://x402scout.com/discover?capability=image-generation`\n\nOption B: MCP server — Claude Desktop connects directly\n\nOption C: npm install -g x402scout\n\nAll free. All instant.\n\n#x402",
        "tags": ["tutorial", "discovery"],
        "priority": 1,
    },
    {
        "id": "tut_003",
        "pillar": "tutorials",
        "platform": "x",
        "content": "x402 integration path I wish I'd known from day 1:\n\n1. Register on x402scout.com (free)\n2. Wrap with ScoutGate for payment proxy\n3. Test: `x402scout scan <url>`\n4. Check trust score in catalog\n\n~10 min total. No facilitator registration.\n\n@base #x402",
        "tags": ["tutorial", "getting_started"],
        "priority": 1,
    },

    # ─────────────────────────────────────────────────────────
    # PILLAR 4: AGENT ECONOMY VISION (Big-picture narrative)
    # ─────────────────────────────────────────────────────────
    {
        "id": "vis_001",
        "pillar": "agent_economy_vision",
        "platform": "x",
        "content": "Subscriptions die in the agent economy.\n\nYour SaaS charges $99/mo because humans use it predictably.\n\nAn AI agent uses it 0 times one week, 10,000 times the next.\n\nPer-call pricing isn't just better — it's the only model that works for machines.\n\n#x402",
        "tags": ["vision", "saas_death"],
        "priority": 1,
    },
    {
        "id": "vis_002",
        "pillar": "agent_economy_vision",
        "platform": "x",
        "content": "Machines paying machines on Base.\n\nThe missing piece: how do they find each other?\n\n1,072 x402 services indexed. More every 6 hours. Agents search, pay, receive.\n\nThis is what the agent economy looks like when it works.\n\nx402scout.com @base #x402",
        "tags": ["vision", "base"],
        "priority": 1,
    },
    {
        "id": "vis_003",
        "pillar": "agent_economy_vision",
        "platform": "x",
        "content": "The agent economy needs three things:\n\n1. Find paid services (discovery)\n2. Pay for them (x402)\n3. Monetize without an ops team (ScoutGate)\n\nAll three exist. All live on Base. All live today.\n\n@base #x402",
        "tags": ["vision", "stack"],
        "priority": 1,
    },
    {
        "id": "vis_004",
        "pillar": "agent_economy_vision",
        "platform": "x",
        "content": "HTTP 402 was defined in 1996.\n\n\"Payment Required — reserved for future use.\"\n\n30 years later, @coinbase implemented it for AI agents on Base.\n\nSometimes the right idea just needs the right moment.\n\n#x402",
        "tags": ["vision", "history"],
        "priority": 2,
    },
    {
        "id": "vis_005",
        "pillar": "agent_economy_vision",
        "platform": "x",
        "content": "Why x402 wins over API keys for agent-to-agent commerce:\n\n• No subscription management\n• No billing dashboards\n• No human approval loop\n• Cryptographic payment proof\n• Sub-cent transactions viable\n\nAPI keys are for humans. x402 is for agents.\n\n#x402",
        "tags": ["vision", "x402_vs_apikeys"],
        "priority": 1,
    },

    # ─────────────────────────────────────────────────────────
    # PILLAR 5: HOT TAKES (Contrarian/competitive intel)
    # — bare, no hashtags: performs better raw
    # ─────────────────────────────────────────────────────────
    {
        "id": "hot_001",
        "pillar": "hot_takes",
        "platform": "x",
        "content": "Unpopular take: x402 doesn't need more facilitators.\n\nIt needs more services worth paying for.\n\nThere are 23+ facilitators. But finding what to *buy* is still hard.\n\nThat's the real bottleneck. That's why we built discovery first.",
        "tags": ["hot_take", "facilitators"],
        "priority": 1,
    },
    {
        "id": "hot_002",
        "pillar": "hot_takes",
        "platform": "x",
        "content": "Hot take: most x402 ecosystem projects won't exist by Q4 2026.\n\nNot because x402 fails — because building announcement-first instead of ship-first ends in inaction.\n\nThe services with real traffic now will compound. The others won't.",
        "tags": ["hot_take", "ecosystem"],
        "priority": 2,
    },
    {
        "id": "hot_003",
        "pillar": "hot_takes",
        "platform": "x",
        "content": "@coinbase's x402 facilitator is free.\n\nBuilding your business model on free infrastructure is a risk most founders underestimate.\n\nIt's free until it isn't. Build your own settlement path as a hedge. That's what RouteNet is for.",
        "tags": ["hot_take", "coinbase", "risk"],
        "priority": 2,
    },
    {
        "id": "hot_004",
        "pillar": "hot_takes",
        "platform": "x",
        "content": "The 'deferred' x402 payment scheme will be bigger than 'exact.'\n\nExact payment = pay before you know if the service works.\nDeferred = pay only on success.\n\nFor enterprise agent deployments, deferred is non-negotiable.\n\nNobody's building it yet.",
        "tags": ["hot_take", "deferred", "enterprise"],
        "priority": 1,
    },

    # ─────────────────────────────────────────────────────────
    # DISCORD-SPECIFIC POSTS (longer, community-oriented)
    # ─────────────────────────────────────────────────────────
    {
        "id": "disc_001",
        "pillar": "build_in_public",
        "platform": "discord_cdp",
        "content": (
            "## 📊 Weekly x402Scout Update\n\n"
            "**1,072 services registered** in the catalog — up from 803 two weeks ago (+33% in 2 weeks)\n\n"
            "**ScoutGate launched** — wrap any API in x402 payments in 30 seconds. "
            "Real on-chain settlement verified on Base mainnet. https://x402-scoutgate.onrender.com\n\n"
            "**6 scan sources running** every 6h: awesome-x402, x402.org, GitHub Search, Smithery, mcp.so, and manual seeds\n\n"
            "The catalog is free to use. Discovery API, MCP server, CLI — all at https://x402scout.com\n\n"
            "Questions? Building with x402? Happy to help 🔧"
        ),
        "tags": ["weekly_update", "growth"],
        "priority": 1,
    },
    {
        "id": "disc_002",
        "pillar": "tutorials",
        "platform": "discord_cdp",
        "content": (
            "## ScoutGate: Wrap Any API in x402 in 30 Seconds\n\n"
            "Got an API you want to monetize? ScoutGate handles everything — no facilitator registration, "
            "no EIP-712 headers, no settlement logic.\n\n"
            "**Quick start:**\n"
            "```bash\n"
            "curl -X POST https://x402-scoutgate.onrender.com/register \\\\\n"
            '  -H "Content-Type: application/json" \\\\\n'
            "  -d '{\"api_url\":\"https://your-api.com/endpoint\",\"wallet_address\":\"0xYOUR_WALLET\","
            "\"price_usd\":0.005,\"name\":\"My API\",\"description\":\"What it does\",\"category\":\"ai\"}'\n"
            "```\n\n"
            "You get back a `proxy_url` — share that URL instead of your direct API. ScoutGate handles "
            "402 responses, payment verification, and settlement. 2% fee per transaction, $0.002 floor.\n\n"
            "Or use the form: https://x402-scoutgate.onrender.com/register\n\n"
            "Your registered API auto-appears in the x402Scout catalog for agents to discover 🤖"
        ),
        "tags": ["tutorial", "scoutgate"],
        "priority": 1,
    },
    {
        "id": "disc_003",
        "pillar": "ecosystem_intel",
        "platform": "discord_cdp",
        "content": (
            "## x402 Ecosystem State — March 2026\n\n"
            "Things I'm tracking across the ecosystem that might be useful:\n\n"
            "📈 **1,072 services** indexed in x402Scout catalog (free: https://x402scout.com/catalog)\n"
            "🏗️ **ScoutGate** — first x402 monetization gateway with zero protocol knowledge required\n"
            "🔍 **Trust Score** — every service rated 0–100 based on uptime, compliance, security\n"
            "💡 **Gap**: pricing intelligence doesn't exist yet (nobody knows what the market charges per category)\n\n"
            "If you're building something in the x402 space and want to be indexed — register at https://x402scout.com\n\n"
            "Heads up: the /discover and /scan endpoints are x402-gated ($0.001/call) so agents can use them "
            "in the wild. The /catalog endpoint is always free."
        ),
        "tags": ["ecosystem", "update"],
        "priority": 2,
    },
]


def get_posts_by_pillar(pillar: str) -> list:
    return [p for p in CONTENT_LIBRARY if p["pillar"] == pillar]


def get_posts_by_platform(platform: str) -> list:
    return [p for p in CONTENT_LIBRARY if p["platform"] in (platform, "all")]


def get_unposted(state_posts: list, platform: str) -> list:
    """Return posts not yet posted to platform, sorted by priority."""
    posted_ids = {p.get("content_id") for p in state_posts if p.get("platform") == platform}
    available = get_posts_by_platform(platform)
    unposted = [p for p in available if p["id"] not in posted_ids]
    return sorted(unposted, key=lambda x: x["priority"])
