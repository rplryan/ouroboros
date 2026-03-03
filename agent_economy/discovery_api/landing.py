"""Landing page HTML for x402scout.com / browser requests to /"""

LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>x402Scout — x402 Service Discovery</title>
<meta name="description" content="Discover 250+ x402-payable APIs for AI agents. Search by category, price, and trust score. Built on the coinbase/x402 micropayment standard.">
<style>
  :root {
    --green: #00ff88;
    --green-dim: #00cc6a;
    --green-faint: rgba(0,255,136,0.08);
    --bg: #050a07;
    --text: #c8e6c9;
    --text-dim: #7ea885;
    --border: rgba(0,255,136,0.18);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  body::before {
    content: '';
    position: fixed;
    top: -30vh;
    left: 50%;
    transform: translateX(-50%);
    width: 90vw;
    height: 90vw;
    max-width: 900px;
    max-height: 900px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(0,255,136,0.04) 0%, rgba(0,255,136,0.02) 40%, transparent 70%);
    border: 1px solid rgba(0,255,136,0.06);
    pointer-events: none;
    z-index: 0;
  }
  .container {
    position: relative;
    z-index: 1;
    width: 100%;
    max-width: 860px;
    padding: 60px 24px 80px;
  }
  header {
    display: flex;
    align-items: center;
    gap: 18px;
    margin-bottom: 48px;
  }
  .logo-wrap img { width: 56px; height: 56px; }
  .brand h1 {
    font-size: 1.9rem;
    color: var(--green);
    letter-spacing: 0.04em;
    font-weight: 700;
  }
  .brand .tagline {
    color: var(--text-dim);
    font-size: 0.85rem;
    margin-top: 4px;
    letter-spacing: 0.06em;
  }
  .hero {
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--green-faint);
    padding: 36px 32px;
    margin-bottom: 40px;
  }
  .hero h2 {
    font-size: 1.5rem;
    color: var(--green);
    margin-bottom: 12px;
    letter-spacing: 0.02em;
  }
  .hero p {
    color: var(--text);
    font-size: 0.95rem;
    line-height: 1.7;
    max-width: 640px;
  }
  .hero p span.accent { color: var(--green); }
  .stats {
    display: flex;
    gap: 32px;
    margin-top: 28px;
    flex-wrap: wrap;
  }
  .stat-item { display: flex; flex-direction: column; gap: 4px; }
  .stat-val {
    font-size: 1.6rem;
    color: var(--green);
    font-weight: 700;
    letter-spacing: 0.02em;
  }
  .stat-label { font-size: 0.75rem; color: var(--text-dim); letter-spacing: 0.08em; text-transform: uppercase; }
  .section-title {
    font-size: 0.72rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text-dim);
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }
  .tools-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
    margin-bottom: 40px;
  }
  .tool-card {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 18px;
    background: rgba(0,255,136,0.03);
    transition: border-color 0.2s, background 0.2s;
  }
  .tool-card:hover {
    border-color: rgba(0,255,136,0.35);
    background: rgba(0,255,136,0.06);
  }
  .tool-name { color: var(--green); font-size: 0.88rem; font-weight: 600; margin-bottom: 6px; }
  .tool-desc { color: var(--text-dim); font-size: 0.78rem; line-height: 1.5; }
  .tool-badge {
    display: inline-block;
    margin-top: 8px;
    font-size: 0.68rem;
    padding: 2px 8px;
    border-radius: 4px;
    letter-spacing: 0.06em;
  }
  .badge-free { background: rgba(0,255,136,0.12); color: var(--green-dim); border: 1px solid rgba(0,255,136,0.2); }
  .badge-paid { background: rgba(255,200,0,0.08); color: #ffd060; border: 1px solid rgba(255,200,0,0.2); }
  .install-block {
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 28px 28px;
    margin-bottom: 40px;
    background: rgba(0,0,0,0.3);
  }
  .code-block {
    background: #0a1a0e;
    border: 1px solid rgba(0,255,136,0.12);
    border-radius: 8px;
    padding: 18px 20px;
    margin: 14px 0;
    overflow-x: auto;
    font-size: 0.8rem;
    line-height: 1.6;
    color: #a5d6a7;
  }
  .code-block .k { color: var(--green); }
  .code-block .s { color: #ffd082; }
  .links-row {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 48px;
  }
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 20px;
    border-radius: 8px;
    font-size: 0.82rem;
    font-family: inherit;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-decoration: none;
    transition: all 0.2s;
    cursor: pointer;
  }
  .btn-primary { background: var(--green); color: #050a07; border: none; }
  .btn-primary:hover { background: var(--green-dim); }
  .btn-secondary { background: transparent; color: var(--green); border: 1px solid var(--border); }
  .btn-secondary:hover { border-color: var(--green); background: var(--green-faint); }
  footer {
    border-top: 1px solid var(--border);
    padding-top: 24px;
    font-size: 0.72rem;
    color: var(--text-dim);
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
    justify-content: center;
  }
  footer a { color: var(--text-dim); text-decoration: none; }
  footer a:hover { color: var(--green); }
  @media (max-width: 600px) {
    .hero { padding: 24px 20px; }
    .stats { gap: 20px; }
    .install-block { padding: 20px 16px; }
    .code-block { font-size: 0.72rem; }
    header { gap: 12px; }
    .brand h1 { font-size: 1.4rem; }
  }
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="logo-wrap">
      <img src="/logo.png" alt="x402Scout logo" width="56" height="56" style="border-radius:50%"/>
    </div>
    <div class="brand">
      <h1>x402Scout</h1>
      <div class="tagline">// x402 service discovery for AI agents</div>
    </div>
  </header>

  <div class="hero">
    <h2>Find x402-payable APIs at runtime</h2>
    <p>
      x402Scout indexes <span class="accent">250+ x402-payable services</span> &mdash; APIs that accept USDC micropayments on Base instead of API keys.
      AI agents query the catalog via <span class="accent">6 MCP tools</span>, get trust scores, uptime data, and
      EdDSA-signed attestations. Built on the open <span class="accent">coinbase/x402</span> payment standard.
    </p>
    <div class="stats">
      <div class="stat-item"><span class="stat-val">250+</span><span class="stat-label">Indexed Services</span></div>
      <div class="stat-item"><span class="stat-val">6</span><span class="stat-label">MCP Tools</span></div>
      <div class="stat-item"><span class="stat-val">$0.01</span><span class="stat-label">Per Query (USDC)</span></div>
      <div class="stat-item"><span class="stat-val">6h</span><span class="stat-label">Auto-Refresh</span></div>
    </div>
  </div>

  <div class="section-title">MCP Tools</div>
  <div class="tools-grid">
    <div class="tool-card">
      <div class="tool-name">x402_discover</div>
      <div class="tool-desc">Quality-ranked search. Filter by category, price range, uptime, and capability tags.</div>
      <span class="tool-badge badge-paid">$0.01 USDC</span>
    </div>
    <div class="tool-card">
      <div class="tool-name">x402_browse</div>
      <div class="tool-desc">Browse the full catalog by category. Returns all services in a human-readable format.</div>
      <span class="tool-badge badge-free">FREE</span>
    </div>
    <div class="tool-card">
      <div class="tool-name">x402_trust</div>
      <div class="tool-desc">ERC-8004 reputation lookup. Trust score, payment history, facilitator flags.</div>
      <span class="tool-badge badge-free">FREE</span>
    </div>
    <div class="tool-card">
      <div class="tool-name">x402_health</div>
      <div class="tool-desc">Live uptime and latency dashboard for any indexed service. Real-time status.</div>
      <span class="tool-badge badge-free">FREE</span>
    </div>
    <div class="tool-card">
      <div class="tool-name">x402_attest</div>
      <div class="tool-desc">EdDSA cryptographic attestation. Verify service identity with JWKS-backed signatures.</div>
      <span class="tool-badge badge-free">FREE</span>
    </div>
    <div class="tool-card">
      <div class="tool-name">x402_register</div>
      <div class="tool-desc">Publish your x402-payable API to the ecosystem catalog. Open registration.</div>
      <span class="tool-badge badge-free">FREE</span>
    </div>
  </div>

  <div class="install-block">
    <div class="section-title">Quick Install &mdash; Claude Desktop / Cursor / Windsurf</div>
    <p style="color: var(--text-dim); font-size: 0.82rem; margin-bottom: 4px;">Add to <code style="color: var(--green)">claude_desktop_config.json</code>:</p>
    <div class="code-block"><span class="k">"x402-discovery"</span>: {<br>&nbsp;&nbsp;<span class="k">"command"</span>: <span class="s">"docker"</span>,<br>&nbsp;&nbsp;<span class="k">"args"</span>: [<span class="s">"run"</span>, <span class="s">"-i"</span>, <span class="s">"--rm"</span>,<br>&nbsp;&nbsp;&nbsp;&nbsp;<span class="s">"ghcr.io/rplryan/x402-discovery-mcp:latest"</span>]<br>}</div>
    <p style="color: var(--text-dim); font-size: 0.82rem; margin-bottom: 4px;">Or use the remote MCP endpoint directly:</p>
    <div class="code-block"><span class="k">"x402-discovery"</span>: {<br>&nbsp;&nbsp;<span class="k">"url"</span>: <span class="s">"https://x402scout.com/mcp"</span><br>}</div>
  </div>

  <div class="links-row">
    <a href="https://github.com/rplryan/x402-discovery-mcp" class="btn btn-primary" target="_blank">&#9733; GitHub</a>
    <a href="/docs" class="btn btn-secondary">API Docs</a>
    <a href="/catalog" class="btn btn-secondary">View Catalog</a>
    <a href="https://github.com/rplryan/x402-discovery-mcp/discussions/1" class="btn btn-secondary" target="_blank">Community</a>
  </div>

  <footer>
    <a href="/privacy">Privacy</a>
    <a href="/terms">Terms</a>
    <a href="mailto:x402scout@proton.me">Support</a>
    <a href="https://github.com/coinbase/x402" target="_blank">coinbase/x402 protocol</a>
    <span style="color: #2d4a33;">&#169; 2026 x402Scout</span>
  </footer>
</div>
</body>
</html>"""
