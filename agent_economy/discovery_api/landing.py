"""Landing page HTML for x402Scout discovery API."""

LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>x402Scout — Discovery Layer for the x402 Agent Economy</title>
<meta name="description" content="Find, verify, and pay for x402-enabled APIs. Built for AI agents, designed for developers.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0a0a;--bg2:#111;--bg3:#161616;--border:#1e1e1e;
  --green:#00ff41;--green-dim:#00cc34;--green-muted:rgba(0,255,65,0.12);
  --yellow:#ffd600;--red:#ff4141;--blue:#41b0ff;
  --text:#e8e8e8;--text-muted:#666;--text-dim:#444;
  --radius:8px;--radius-lg:14px;
  --mono:'JetBrains Mono',monospace;--sans:'Inter',sans-serif;
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:var(--green);text-decoration:none}
a:hover{text-decoration:underline}

/* ── SCROLLBAR ── */
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:#2a2a2a}

/* ── NAV ── */
nav{
  position:sticky;top:0;z-index:100;
  background:rgba(10,10,10,0.92);backdrop-filter:blur(16px);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 2rem;height:56px;
}
.nav-logo{
  font-family:var(--mono);font-size:1.05rem;font-weight:600;
  color:var(--green);letter-spacing:0.02em;display:flex;align-items:center;gap:0.4rem;
}
.nav-logo .hex{
  display:inline-block;
  animation:pulse-glow 3s ease-in-out infinite;
}
@keyframes pulse-glow{
  0%,100%{text-shadow:0 0 4px var(--green),0 0 12px rgba(0,255,65,0.3)}
  50%{text-shadow:0 0 8px var(--green),0 0 24px rgba(0,255,65,0.6),0 0 40px rgba(0,255,65,0.2)}
}
.nav-links{display:flex;align-items:center;gap:1.5rem}
.nav-links a{color:var(--text-muted);font-size:0.85rem;font-weight:500;transition:color 0.2s}
.nav-links a:hover{color:var(--text);text-decoration:none}
.nav-stat{
  font-family:var(--mono);font-size:0.8rem;color:var(--text-muted);
  display:flex;align-items:center;gap:0.35rem;
  background:var(--bg3);border:1px solid var(--border);
  border-radius:20px;padding:0.2rem 0.75rem;
}
.nav-stat .dot{
  width:6px;height:6px;border-radius:50%;background:var(--green);
  box-shadow:0 0 6px var(--green);
  animation:blink 2s ease-in-out infinite;
}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.4}}

/* ── SECTIONS ── */
section{padding:5rem 2rem;max-width:1100px;margin:0 auto}
h2{font-size:1.6rem;font-weight:700;margin-bottom:0.5rem;color:#fff}
.section-label{
  font-family:var(--mono);font-size:0.72rem;color:var(--green);
  text-transform:uppercase;letter-spacing:0.12em;margin-bottom:0.75rem;display:block;
}

/* ── HERO ── */
#hero{
  max-width:100%;padding:6rem 2rem 4rem;
  display:flex;flex-direction:column;align-items:center;text-align:center;
  position:relative;overflow:hidden;
}
#hero::before{
  content:'';position:absolute;inset:0;
  background:radial-gradient(ellipse 80% 60% at 50% 0%, rgba(0,255,65,0.06) 0%, transparent 70%);
  pointer-events:none;
}
.scanline{
  position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,var(--green),transparent);
  opacity:0.4;animation:scan 4s linear infinite;
}
@keyframes scan{0%{top:-2px;opacity:0}10%{opacity:0.4}90%{opacity:0.4}100%{top:100%;opacity:0}}
.hero-title{
  font-size:clamp(2rem,5vw,3.2rem);font-weight:700;line-height:1.2;
  color:#fff;max-width:800px;margin-bottom:1.25rem;
}
.hero-title span{color:var(--green)}
.hero-sub{
  font-size:1.1rem;color:var(--text-muted);max-width:580px;
  margin-bottom:2.5rem;line-height:1.7;
}
.hero-ctas{display:flex;gap:1rem;flex-wrap:wrap;justify-content:center;margin-bottom:3rem}
.btn{
  display:inline-flex;align-items:center;gap:0.4rem;
  font-family:var(--sans);font-size:0.9rem;font-weight:600;
  padding:0.65rem 1.5rem;border-radius:var(--radius);cursor:pointer;
  transition:all 0.2s;text-decoration:none!important;border:none;
}
.btn-primary{background:var(--green);color:#000}
.btn-primary:hover{background:#00e639;box-shadow:0 0 20px rgba(0,255,65,0.35)}
.btn-outline{
  background:transparent;color:var(--green);
  border:1px solid var(--green);
}
.btn-outline:hover{background:var(--green-muted)}
.stats-bar{
  display:flex;gap:3rem;flex-wrap:wrap;justify-content:center;
  padding-top:2.5rem;border-top:1px solid var(--border);width:100%;max-width:700px;
}
.stat-item{display:flex;flex-direction:column;align-items:center;gap:0.2rem}
.stat-num{
  font-family:var(--mono);font-size:2rem;font-weight:600;color:var(--green);
  text-shadow:0 0 20px rgba(0,255,65,0.4);
}
.stat-label{font-size:0.8rem;color:var(--text-muted)}

/* ── QUICKSTART ── */
#quickstart{border-top:1px solid var(--border)}
.tabs{display:flex;gap:0;border:1px solid var(--border);border-radius:var(--radius);
  width:fit-content;margin-bottom:1.5rem;overflow:hidden}
.tab-btn{
  font-family:var(--mono);font-size:0.82rem;font-weight:500;
  padding:0.5rem 1.2rem;background:transparent;color:var(--text-muted);
  border:none;cursor:pointer;transition:all 0.2s;border-right:1px solid var(--border);
}
.tab-btn:last-child{border-right:none}
.tab-btn.active{background:var(--green-muted);color:var(--green)}
.tab-btn:hover:not(.active){background:var(--bg3);color:var(--text)}
.tab-pane{display:none}
.tab-pane.active{display:block}
pre{
  background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius);padding:1.25rem 1.5rem;
  font-family:var(--mono);font-size:0.82rem;line-height:1.7;
  overflow-x:auto;color:#c9d1d9;
}
pre .comment{color:var(--text-dim)}
pre .cmd{color:var(--green)}
pre .url{color:var(--blue)}
pre .flag{color:var(--yellow)}

/* ── PRODUCTS ── */
#products{border-top:1px solid var(--border)}
.products-grid{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  gap:1.25rem;margin-top:1.75rem;
}
.product-card{
  background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius-lg);
  padding:1.5rem;transition:border-color 0.25s,transform 0.2s;
  display:flex;flex-direction:column;gap:0.75rem;
}
.product-card:hover{border-color:rgba(0,255,65,0.35);transform:translateY(-2px)}
.product-card.featured{border-color:rgba(0,255,65,0.2);background:linear-gradient(135deg,var(--bg2) 0%,rgba(0,255,65,0.03) 100%)}
.product-header{display:flex;align-items:center;gap:0.75rem}
.product-icon{
  width:40px;height:40px;border-radius:8px;
  background:var(--green-muted);border:1px solid rgba(0,255,65,0.2);
  display:flex;align-items:center;justify-content:center;
  font-size:1.1rem;flex-shrink:0;
}
.product-name{font-family:var(--mono);font-size:1rem;font-weight:600;color:#fff}
.product-tag{font-family:var(--mono);font-size:0.68rem;color:var(--green);background:var(--green-muted);border:1px solid rgba(0,255,65,0.2);padding:0.15rem 0.5rem;border-radius:4px;margin-left:auto;white-space:nowrap}
.product-desc{font-size:0.85rem;color:var(--text-muted);line-height:1.6}
.product-features{list-style:none;display:flex;flex-direction:column;gap:0.35rem}
.product-features li{font-size:0.8rem;color:var(--text-muted);display:flex;align-items:center;gap:0.5rem}
.product-features li::before{content:'→';color:var(--green);font-family:var(--mono);font-size:0.75rem;flex-shrink:0}
.product-footer{display:flex;align-items:center;gap:0.75rem;margin-top:auto;padding-top:0.5rem;border-top:1px solid var(--border)}
.product-link{font-family:var(--mono);font-size:0.78rem;color:var(--green);font-weight:500}
.product-link:hover{text-decoration:underline}
.product-link-secondary{font-family:var(--mono);font-size:0.78rem;color:var(--text-muted)}
.product-link-secondary:hover{color:var(--text);text-decoration:underline}

/* ── CATALOG ── */
#catalog{border-top:1px solid var(--border)}
.catalog-controls{display:flex;flex-direction:column;gap:1rem;margin-bottom:1.75rem}
.search-wrap{position:relative}
.search-wrap input{
  width:100%;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius);padding:0.7rem 1rem 0.7rem 2.5rem;
  font-family:var(--sans);font-size:0.9rem;color:var(--text);outline:none;
  transition:border-color 0.2s;
}
.search-wrap input:focus{border-color:var(--green)}
.search-wrap input::placeholder{color:var(--text-dim)}
.search-icon{
  position:absolute;left:0.8rem;top:50%;transform:translateY(-50%);
  color:var(--text-dim);font-size:0.9rem;pointer-events:none;
}
.filter-pills{display:flex;gap:0.5rem;flex-wrap:wrap}
.pill{
  font-family:var(--mono);font-size:0.75rem;padding:0.3rem 0.8rem;
  border:1px solid var(--border);border-radius:20px;
  background:transparent;color:var(--text-muted);cursor:pointer;transition:all 0.2s;
}
.pill.active{background:var(--green-muted);border-color:var(--green);color:var(--green)}
.pill:hover:not(.active){border-color:#333;color:var(--text)}
.cards-grid{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
  gap:1rem;margin-bottom:1.5rem;
}
.card{
  background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius-lg);
  padding:1.25rem;transition:border-color 0.2s,transform 0.2s;
}
.card:hover{border-color:#2a2a2a;transform:translateY(-1px)}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.6rem}
.card-name{font-weight:600;font-size:0.95rem;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70%}
.badge{
  font-family:var(--mono);font-size:0.68rem;padding:0.2rem 0.55rem;
  border-radius:4px;background:var(--green-muted);color:var(--green);
  border:1px solid rgba(0,255,65,0.2);white-space:nowrap;
}
.card-url{
  font-family:var(--mono);font-size:0.75rem;color:var(--text-muted);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  margin-bottom:0.75rem;
}
.card-desc{font-size:0.82rem;color:var(--text-muted);margin-bottom:0.9rem;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.trust-row{display:flex;align-items:center;gap:0.6rem;margin-bottom:0.6rem}
.trust-label{font-size:0.72rem;color:var(--text-dim);font-family:var(--mono);white-space:nowrap}
.trust-track{flex:1;height:3px;background:#1a1a1a;border-radius:2px;overflow:hidden}
.trust-bar{height:100%;border-radius:2px;transition:width 0.5s ease}
.trust-val{font-family:var(--mono);font-size:0.72rem;color:var(--text-muted);min-width:2rem;text-align:right}
.card-footer{display:flex;justify-content:space-between;align-items:center}
.card-price{font-family:var(--mono);font-size:0.78rem;color:var(--green)}
.card-status{font-size:0.72rem;color:var(--text-dim)}
.card-status.up{color:var(--green)}
.card-status.down{color:var(--red)}
.card-status.pending{color:var(--text-dim)}
.loadmore-wrap{text-align:center;margin-top:0.5rem}
#load-more{display:none}
.catalog-empty{
  text-align:center;padding:4rem 1rem;color:var(--text-muted);
  font-family:var(--mono);font-size:0.9rem;
}
.catalog-loading{
  text-align:center;padding:4rem 1rem;color:var(--text-muted);
  display:flex;flex-direction:column;align-items:center;gap:1rem;
}
.spinner{
  width:32px;height:32px;border:2px solid var(--border);
  border-top-color:var(--green);border-radius:50%;
  animation:spin 0.8s linear infinite;
}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── API REF ── */
#api{border-top:1px solid var(--border)}
.api-table{width:100%;border-collapse:collapse;margin-top:1rem}
.api-table th{
  font-family:var(--mono);font-size:0.72rem;text-transform:uppercase;
  letter-spacing:0.08em;color:var(--text-dim);padding:0.6rem 1rem;
  border-bottom:1px solid var(--border);text-align:left;
}
.api-table td{
  padding:0.75rem 1rem;border-bottom:1px solid rgba(30,30,30,0.6);
  font-size:0.85rem;vertical-align:top;
}
.api-table tr:last-child td{border-bottom:none}
.api-table tr:hover td{background:var(--bg3)}
.method{
  font-family:var(--mono);font-size:0.72rem;font-weight:600;
  padding:0.2rem 0.5rem;border-radius:4px;display:inline-block;
}
.method.get{background:rgba(65,176,255,0.12);color:var(--blue);border:1px solid rgba(65,176,255,0.2)}
.method.post{background:rgba(255,214,0,0.1);color:var(--yellow);border:1px solid rgba(255,214,0,0.2)}
.endpoint-path{font-family:var(--mono);font-size:0.82rem;color:var(--text)}
.auth-free{color:var(--green);font-size:0.78rem}
.auth-paid{color:var(--yellow);font-size:0.78rem}

/* ── REGISTER ── */
#register{border-top:1px solid var(--border)}
.register-form{
  background:var(--bg2);border:1px solid var(--border);
  border-radius:var(--radius-lg);padding:2rem;max-width:560px;
}
.form-group{margin-bottom:1.25rem}
.form-group label{
  display:block;font-size:0.8rem;font-weight:500;color:var(--text-muted);
  margin-bottom:0.4rem;font-family:var(--mono);
}
.form-group input,.form-group select{
  width:100%;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius);padding:0.65rem 1rem;
  font-family:var(--sans);font-size:0.9rem;color:var(--text);
  outline:none;transition:border-color 0.2s;
  -webkit-appearance:none;appearance:none;
}
.form-group input:focus,.form-group select:focus{border-color:var(--green)}
.form-group select{
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%23666' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 1rem center;padding-right:2.5rem;
}
.form-note{font-size:0.78rem;color:var(--text-muted);margin-top:1rem;line-height:1.5}
.form-note strong{color:var(--green)}
#register-result{margin-top:1rem;padding:0.75rem 1rem;border-radius:var(--radius);font-size:0.85rem;display:none}
#register-result.success{background:rgba(0,255,65,0.08);border:1px solid rgba(0,255,65,0.2);color:var(--green)}
#register-result.error{background:rgba(255,65,65,0.08);border:1px solid rgba(255,65,65,0.2);color:var(--red)}

/* ── FOOTER ── */
footer{
  border-top:1px solid var(--border);padding:3rem 2rem;
  max-width:1100px;margin:0 auto;
  display:flex;flex-direction:column;align-items:center;gap:1.5rem;text-align:center;
}
.footer-logo{font-family:var(--mono);font-size:1rem;color:var(--green)}
.footer-tagline{font-size:0.82rem;color:var(--text-muted)}
.footer-links{display:flex;gap:1.5rem;flex-wrap:wrap;justify-content:center}
.footer-links a{font-size:0.82rem;color:var(--text-dim);transition:color 0.2s}
.footer-links a:hover{color:var(--text);text-decoration:none}
.footer-copy{font-family:var(--mono);font-size:0.72rem;color:var(--text-dim)}

/* ── RESPONSIVE ── */
@media(max-width:768px){
  nav{padding:0 1rem}
  .nav-links{display:none}
  section{padding:3.5rem 1rem}
  .cards-grid{grid-template-columns:1fr}
  .stats-bar{gap:2rem}
  .api-table{font-size:0.78rem}
  .api-table th,.api-table td{padding:0.5rem 0.6rem}
  .register-form{padding:1.25rem}
}
@media(max-width:480px){
  .hero-ctas{flex-direction:column;align-items:center}
  .btn{width:100%;justify-content:center}
  .stats-bar{gap:1.5rem}
  .stat-num{font-size:1.5rem}
}
</style>
</head>
<body>

<!-- NAV -->
<nav>
  <div class="nav-logo">
    <span class="hex">⬡</span> x402Scout
  </div>
  <div class="nav-links">
    <a href="#products">Products</a>
    <a href="#catalog">Catalog</a>
    <a href="#api">Docs</a>
    <a href="https://github.com/rplryan/ouroboros" target="_blank" rel="noopener">GitHub</a>
    <a href="#quickstart">MCP</a>
    <a href="#quickstart">CLI</a>
  </div>
  <div class="nav-stat">
    <span class="dot"></span>
    <span id="nav-count">— services</span>
  </div>
</nav>

<!-- HERO -->
<div id="hero">
  <div class="scanline"></div>
  <span class="section-label">x402 Protocol · Base Mainnet · USDC</span>
  <h1 class="hero-title">
    The Discovery Layer for the<br><span>x402 Agent Economy</span>
  </h1>
  <p class="hero-sub">
    Find, verify, and pay for x402-enabled APIs.
    Built for AI agents, designed for developers.
  </p>
  <div class="hero-ctas">
    <a href="#catalog" class="btn btn-primary">Browse Catalog →</a>
    <a href="#register" class="btn btn-outline">Add Your Service</a>
  </div>
  <div class="stats-bar">
    <div class="stat-item">
      <span class="stat-num" id="stat-services">—</span>
      <span class="stat-label">live services</span>
    </div>
    <div class="stat-item">
      <span class="stat-num" id="stat-categories">—</span>
      <span class="stat-label">categories</span>
    </div>
    <div class="stat-item">
      <span class="stat-num" id="stat-trust">—</span>
      <span class="stat-label">avg trust score</span>
    </div>
  </div>
</div>

<!-- PRODUCTS -->
<section id="products">
  <span class="section-label">First-Party Products</span>
  <h2>The x402Scout Ecosystem</h2>
  <p style="color:var(--text-muted);font-size:0.95rem;margin-top:0.4rem;max-width:600px">A suite of tools for every layer of the x402 payment stack — discover, route, monetize.</p>
  <div class="products-grid">

    <!-- x402Scout (this product) -->
    <div class="product-card featured">
      <div class="product-header">
        <div class="product-icon">⬡</div>
        <span class="product-name">x402Scout</span>
        <span class="product-tag">Discovery</span>
      </div>
      <p class="product-desc">The canonical registry for x402-enabled services. Auto-scanned every 6h, trust-scored, MCP-native. The entry point for agents finding APIs to pay.</p>
      <ul class="product-features">
        <li>710+ services indexed with trust scores (0–100)</li>
        <li>MCP endpoint — works with Claude, Cursor, and any MCP client</li>
        <li>CLI: <code style="font-family:var(--mono);font-size:0.78rem;color:var(--green)">npm i -g x402scout</code></li>
        <li>6 scan sources, auto-updated every 6 hours</li>
      </ul>
      <div class="product-footer">
        <a href="https://x402scout.com/catalog" class="product-link">Browse Catalog →</a>
        <a href="https://x402scout.com/mcp" class="product-link-secondary">/mcp endpoint</a>
        <a href="https://github.com/rplryan/x402-discovery-mcp" target="_blank" rel="noopener" class="product-link-secondary">GitHub</a>
      </div>
    </div>

    <!-- ScoutGate -->
    <div class="product-card featured">
      <div class="product-header">
        <div class="product-icon">⬢</div>
        <span class="product-name">ScoutGate</span>
        <span class="product-tag">Monetization</span>
      </div>
      <p class="product-desc">Wrap any existing API in x402 payments in 30 seconds. Paste your URL, set a price, get a proxy — no x402 knowledge required. Auto-listed in the catalog.</p>
      <ul class="product-features">
        <li>Register in one API call — URL + wallet + price</li>
        <li>Handles EIP-712 signing, 402 headers, USDC settlement</li>
        <li>Real on-chain settlements verified on Base mainnet</li>
        <li>2% fee per transaction (min $0.002) — you keep the rest</li>
      </ul>
      <div class="product-footer">
        <a href="https://x402-scoutgate.onrender.com" target="_blank" rel="noopener" class="product-link">Try ScoutGate →</a>
        <a href="https://x402-scoutgate.onrender.com/docs" target="_blank" rel="noopener" class="product-link-secondary">API Docs</a>
      </div>
    </div>

    <!-- RouteNet -->
    <div class="product-card">
      <div class="product-header">
        <div class="product-icon">◈</div>
        <span class="product-name">RouteNet</span>
        <span class="product-tag">Routing</span>
      </div>
      <p class="product-desc">Intelligent routing layer for x402 payments. Selects the optimal facilitator and endpoint for each request based on price, latency, and trust score.</p>
      <ul class="product-features">
        <li>Multi-facilitator routing with automatic fallback</li>
        <li>Optimizes for price, speed, or reliability</li>
        <li>REST API — drop-in replacement for direct x402 calls</li>
      </ul>
      <div class="product-footer">
        <a href="https://x402-routenet.onrender.com" target="_blank" rel="noopener" class="product-link">Visit RouteNet →</a>
      </div>
    </div>

  </div>
</section>

<!-- QUICKSTART -->
<section id="quickstart">
  <span class="section-label">Integration</span>
  <h2>Quick Start</h2>
  <p style="color:var(--text-muted);margin-bottom:1.75rem;max-width:560px">
    Connect in seconds via MCP, REST, or CLI. The catalog endpoint is always free.
  </p>
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab(event,'mcp')">MCP (Claude)</button>
    <button class="tab-btn" onclick="switchTab(event,'rest')">REST API</button>
    <button class="tab-btn" onclick="switchTab(event,'cli')">CLI</button>
  </div>
  <div id="tab-mcp" class="tab-pane active">
<pre><span class="comment"># Add to Claude Desktop (Settings → MCP):</span>
<span class="url">https://x402scout.com/mcp</span>

<span class="comment"># Or add to your claude_desktop_config.json:</span>
{
  "mcpServers": {
    "x402scout": {
      "url": <span class="url">"https://x402scout.com/mcp"</span>,
      "transport": "streamable-http"
    }
  }
}</pre>
  </div>
  <div id="tab-rest" class="tab-pane">
<pre><span class="comment"># Search services (costs $0.010 USDC via x402)</span>
<span class="cmd">curl</span> <span class="url">"https://x402scout.com/discover?q=translation"</span>

<span class="comment"># Full catalog — always FREE</span>
<span class="cmd">curl</span> <span class="url">"https://x402scout.com/catalog"</span>

<span class="comment"># Scan a URL for x402 compliance</span>
<span class="cmd">curl</span> <span class="flag">-X POST</span> <span class="url">"https://x402scout.com/scan"</span> <span class="flag">\\
  -H</span> "Content-Type: application/json" <span class="flag">\\
  -d</span> '{"url": "https://your-service.com/api"}'

<span class="comment"># Register your service</span>
<span class="cmd">curl</span> <span class="flag">-X POST</span> <span class="url">"https://x402scout.com/register"</span> <span class="flag">\\
  -H</span> "Content-Type: application/json" <span class="flag">\\
  -d</span> '{"url":"https://your-service.com/api","category":"utility"}'</pre>
  </div>
  <div id="tab-cli" class="tab-pane">
<pre><span class="cmd">npm install -g x402scout</span>

<span class="comment"># Search the catalog</span>
<span class="cmd">x402scout search</span> translation

<span class="comment"># View top services by trust score</span>
<span class="cmd">x402scout top</span> 10

<span class="comment"># Scan any URL for x402 compliance</span>
<span class="cmd">x402scout scan</span> <span class="url">https://your-service.com/api</span>

<span class="comment"># Register your service</span>
<span class="cmd">x402scout register</span> <span class="url">https://your-service.com/api</span> <span class="flag">--category</span> utility</pre>
  </div>
</section>

<!-- CATALOG -->
<section id="catalog">
  <span class="section-label">Live Registry</span>
  <h2>Service Catalog</h2>
  <p style="color:var(--text-muted);margin-bottom:1.75rem;max-width:560px">
    All registered x402-compatible services, updated continuously.
    Catalog browsing is always free — no wallet required.
  </p>
  <div class="catalog-controls">
    <div class="search-wrap">
      <span class="search-icon">⌕</span>
      <input type="text" id="search-input" placeholder="Search 646+ services..." oninput="filterCatalog()">
    </div>
    <div class="filter-pills" id="filter-pills">
      <button class="pill active" data-cat="all" onclick="setCategoryFilter(this,'all')">All</button>
    </div>
  </div>
  <div id="cards-container">
    <div class="catalog-loading">
      <div class="spinner"></div>
      <span style="font-family:var(--mono);font-size:0.8rem">Loading catalog…</span>
    </div>
  </div>
  <div class="loadmore-wrap">
    <button id="load-more" class="btn btn-outline" onclick="loadMore()">Load more</button>
  </div>
</section>

<!-- API REFERENCE -->
<section id="api">
  <span class="section-label">Reference</span>
  <h2>API Endpoints</h2>
  <p style="color:var(--text-muted);margin-bottom:1.75rem;max-width:560px">
    Base URL: <code style="font-family:var(--mono);color:var(--green)">https://x402scout.com</code>
  </p>
  <table class="api-table">
    <thead>
      <tr>
        <th>Method</th><th>Endpoint</th><th>Description</th><th>Auth</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><span class="method get">GET</span></td>
        <td><span class="endpoint-path">/</span></td>
        <td>This landing page</td>
        <td><span class="auth-free">Free</span></td>
      </tr>
      <tr>
        <td><span class="method get">GET</span></td>
        <td><span class="endpoint-path">/catalog</span></td>
        <td>Full paginated service registry. Supports <code>?limit=</code> &amp; <code>?offset=</code></td>
        <td><span class="auth-free">Free</span></td>
      </tr>
      <tr>
        <td><span class="method get">GET</span></td>
        <td><span class="endpoint-path">/discover</span></td>
        <td>Semantic search with ranking. <code>?q=</code> query param required</td>
        <td><span class="auth-paid">$0.010 USDC (x402)</span></td>
      </tr>
      <tr>
        <td><span class="method post">POST</span></td>
        <td><span class="endpoint-path">/scan</span></td>
        <td>Scan a URL for x402 compliance and trust score</td>
        <td><span class="auth-paid">$0.010 USDC (x402)</span></td>
      </tr>
      <tr>
        <td><span class="method post">POST</span></td>
        <td><span class="endpoint-path">/register</span></td>
        <td>Register a new x402-compatible service</td>
        <td><span class="auth-free">Free</span></td>
      </tr>
      <tr>
        <td><span class="method get">GET</span></td>
        <td><span class="endpoint-path">/.well-known/x402-discovery</span></td>
        <td>Bazaar-compatible x402 discovery metadata</td>
        <td><span class="auth-free">Free</span></td>
      </tr>
      <tr>
        <td><span class="method get">GET</span></td>
        <td><span class="endpoint-path">/mcp</span></td>
        <td>Streamable HTTP MCP endpoint for Claude &amp; agents</td>
        <td><span class="auth-free">Free</span></td>
      </tr>
      <tr>
        <td><span class="method get">GET</span></td>
        <td><span class="endpoint-path">/health/{id}</span></td>
        <td>Live health check for a registered service by ID</td>
        <td><span class="auth-paid">$0.001 USDC (x402)</span></td>
      </tr>
    </tbody>
  </table>
</section>

<!-- REGISTER -->
<section id="register">
  <span class="section-label">Submit</span>
  <h2>Add Your Service</h2>
  <p style="color:var(--text-muted);margin-bottom:1.75rem;max-width:560px">
    Register any x402-compatible endpoint. Your service will be scanned
    and assigned a trust score within 6 hours.
  </p>
  <div class="register-form">
    <div class="form-group">
      <label>Service URL</label>
      <input type="url" id="reg-url" placeholder="https://your-service.com/api" required>
    </div>
    <div class="form-group">
      <label>Category</label>
      <select id="reg-category">
        <option value="">Select a category</option>
        <option value="agent">Agent</option>
        <option value="compute">Compute</option>
        <option value="data">Data</option>
        <option value="finance">Finance</option>
        <option value="generation">Generation</option>
        <option value="research">Research</option>
        <option value="search">Search</option>
        <option value="storage">Storage</option>
        <option value="translation">Translation</option>
        <option value="utility">Utility</option>
        <option value="other">Other</option>
      </select>
    </div>
    <div class="form-group">
      <label>Service Name <span style="color:var(--text-dim)">(optional)</span></label>
      <input type="text" id="reg-name" placeholder="My Awesome API">
    </div>
    <button class="btn btn-primary" onclick="submitRegistration()" style="width:100%">
      Register Service →
    </button>
    <div id="register-result"></div>
    <p class="form-note">
      <strong>Registration is free.</strong> Your service will be automatically scanned
      for x402 compliance, response time, and uptime. Results appear in the catalog
      within 6 hours.
    </p>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <div>
    <div class="footer-logo">⬡ x402Scout</div>
    <div class="footer-tagline">Built for the x402 agent economy</div>
  </div>
  <div class="footer-links">
    <a href="https://github.com/rplryan/ouroboros" target="_blank" rel="noopener">GitHub</a>
    <a href="https://www.npmjs.com/package/x402scout" target="_blank" rel="noopener">npm</a>
    <a href="https://pypi.org/project/x402scout/" target="_blank" rel="noopener">PyPI</a>
    <a href="#mcp">MCP Registry</a>
    <a href="/health">Status</a>
  </div>
  <div class="footer-copy">
    x402scout.com &nbsp;·&nbsp; x402scout@proton.me
  </div>
</footer>

<script>
// ── STATE ──
let allServices = [];
let filteredServices = [];
let displayedCount = 0;
const PAGE_SIZE = 50;
let activeCategory = 'all';

// ── TABS ──
function switchTab(e, name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  e.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}

// ── CATALOG FETCH ──
async function fetchCatalog() {
  try {
    const res = await fetch('/catalog?limit=1000');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const services = data.endpoints || data.services || data.results || data || [];
    return Array.isArray(services) ? services : [];
  } catch (e) {
    console.warn('Catalog fetch failed:', e);
    return [];
  }
}

async function fetchStats() {
  try {
    const res = await fetch('/stats');
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

// ── RENDER ──
function trustColor(score) {
  if (score == null) return '#444';
  if (score >= 70) return '#00ff41';
  if (score >= 40) return '#ffd600';
  return '#ff4141';
}

function statusHtml(s) {
  if (!s || s === 'unverified' || s === 'unknown' || s === 'pending') {
    return `<span class="card-status pending">◌ pending check</span>`;
  }
  const up = s === 'up' || s === 'healthy' || s === 'ok' || s === 'verified_up';
  const cls = up ? 'up' : 'down';
  const label = up ? '● online' : '○ offline';
  return `<span class="card-status ${cls}">${label}</span>`;
}

function renderCard(svc) {
  const trust = svc.trust_score != null ? Math.round(svc.trust_score) : null;
  const trustW = trust != null ? trust : 0;
  const trustC = trustColor(trust);
  const trustLabel = trust != null ? trust : '—';
  const name = svc.name || svc.url || 'Unnamed';
  const url = svc.url || '';
  const cat = svc.category || 'other';
  const desc = svc.description || '';
  const price = svc.price_usd ? `$${parseFloat(svc.price_usd).toFixed(3)} USDC` : '';

  return `<div class="card">
    <div class="card-head">
      <span class="card-name" title="${escHtml(name)}">${escHtml(name)}</span>
      <span class="badge">${escHtml(cat)}</span>
    </div>
    <div class="card-url" title="${escHtml(url)}">${escHtml(url)}</div>
    ${desc ? `<div class="card-desc">${escHtml(desc)}</div>` : ''}
    <div class="trust-row">
      <span class="trust-label">trust</span>
      <div class="trust-track"><div class="trust-bar" style="width:${trustW}%;background:${trustC}"></div></div>
      <span class="trust-val">${trustLabel}</span>
    </div>
    <div class="card-footer">
      <span class="card-price">${price}</span>
      ${statusHtml(svc.health_status)}
    </div>
  </div>`;
}

function escHtml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function renderGrid() {
  const container = document.getElementById('cards-container');
  const btn = document.getElementById('load-more');
  if (filteredServices.length === 0) {
    container.innerHTML = '<div class="catalog-empty">No services found matching your search.</div>';
    btn.style.display = 'none';
    return;
  }
  const slice = filteredServices.slice(0, displayedCount);
  container.innerHTML = `<div class="cards-grid">${slice.map(renderCard).join('')}</div>`;
  btn.style.display = filteredServices.length > displayedCount ? 'inline-flex' : 'none';
}

function loadMore() {
  displayedCount = Math.min(displayedCount + PAGE_SIZE, filteredServices.length);
  renderGrid();
}

// ── FILTERS ──
function buildCategoryPills(services) {
  const cats = new Set();
  services.forEach(s => { if (s.category) cats.add(s.category); });
  const pills = document.getElementById('filter-pills');
  const extras = Array.from(cats).sort().map(cat =>
    `<button class="pill" data-cat="${escHtml(cat)}" onclick="setCategoryFilter(this,'${escHtml(cat)}')">${escHtml(cat)}</button>`
  ).join('');
  pills.innerHTML = `<button class="pill active" data-cat="all" onclick="setCategoryFilter(this,'all')">All</button>${extras}`;
}

function setCategoryFilter(el, cat) {
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  activeCategory = cat;
  applyFilters();
}

function filterCatalog() { applyFilters(); }

function applyFilters() {
  const q = (document.getElementById('search-input').value || '').toLowerCase().trim();
  filteredServices = allServices.filter(s => {
    const inCat = activeCategory === 'all' || s.category === activeCategory;
    if (!inCat) return false;
    if (!q) return true;
    const haystack = ((s.name || '') + ' ' + (s.url || '') + ' ' + (s.description || '') + ' ' + (s.category || '')).toLowerCase();
    return haystack.includes(q);
  });
  displayedCount = PAGE_SIZE;
  renderGrid();
}

// ── LIVE STATS ──
function updateStats(services) {
  const total = services.length;
  const cats = new Set(services.map(s => s.category).filter(Boolean)).size;
  const scores = services.map(s => s.trust_score).filter(v => v != null);
  const avgTrust = scores.length ? Math.round(scores.reduce((a,b) => a+b, 0) / scores.length) : null;

  const animNum = (el, val) => {
    if (!el || val == null) { if (el) el.textContent = '—'; return; }
    let cur = 0;
    const step = Math.ceil(val / 40);
    const timer = setInterval(() => {
      cur = Math.min(cur + step, val);
      el.textContent = cur;
      if (cur >= val) clearInterval(timer);
    }, 30);
  };
  animNum(document.getElementById('stat-categories'), cats);
  animNum(document.getElementById('stat-trust'), avgTrust);
}

async function updateNavCount() {
  const data = await fetchStats();
  const el = document.getElementById('nav-count');
  if (data && el) el.textContent = (data.total_services || data.active_services || 0) + ' services';
}

// ── REGISTER ──
async function submitRegistration() {
  const url = document.getElementById('reg-url').value.trim();
  const category = document.getElementById('reg-category').value;
  const name = document.getElementById('reg-name').value.trim();
  const resultEl = document.getElementById('register-result');

  if (!url) { showResult(resultEl, 'error', 'Please enter a service URL.'); return; }

  const body = { url };
  if (category) body.category = category;
  if (name) body.name = name;

  try {
    const res = await fetch('/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (res.ok) {
      showResult(resultEl, 'success', '✓ Registered! Your service will be scanned within 6 hours.');
      document.getElementById('reg-url').value = '';
      document.getElementById('reg-name').value = '';
      document.getElementById('reg-category').value = '';
    } else {
      const rawDetail = data.detail || data.error || 'Registration failed.';
      const errMsg = Array.isArray(rawDetail)
        ? rawDetail.map(e => (e.msg || JSON.stringify(e)) + (e.loc && e.loc.length ? ' (' + e.loc.join('.') + ')' : '')).join('; ')
        : (typeof rawDetail === 'string' ? rawDetail : JSON.stringify(rawDetail));
      showResult(resultEl, 'error', errMsg);
    }
  } catch (e) {
    showResult(resultEl, 'error', 'Network error — please try again.');
  }
}

function showResult(el, type, msg) {
  el.className = type;
  el.textContent = msg;
  el.style.display = 'block';
}

// ── INIT ──
(async function init() {
  // Stats — populate immediately from /stats (fast, no catalog needed)
  const statsPromise = fetchStats();
  statsPromise.then(data => {
    if (!data) return;
    const setEl = (id, val) => { const el = document.getElementById(id); if (el && val != null) el.textContent = val; };
    setEl('stat-services', (data.total_services || data.active_services || 0).toLocaleString());
    setEl('stat-categories', data.categories || 0);
    if (data.avg_trust_score != null) setEl('stat-trust', data.avg_trust_score + '/100');
    const navEl = document.getElementById('nav-count');
    if (navEl) navEl.textContent = (data.total_services || data.active_services || 0) + ' services';
  });
  setInterval(updateNavCount, 30000);

  // Full catalog
  const services = await fetchCatalog();
  allServices = services;
  filteredServices = services;
  displayedCount = PAGE_SIZE;

  if (services.length > 0) {
    buildCategoryPills(services);
    updateStats(services);
    // Update search placeholder with real count
    const inp = document.getElementById('search-input');
    if (inp) inp.placeholder = `Search ${services.length}+ services…`;
    // Update nav count immediately
    const navEl = document.getElementById('nav-count');
    if (navEl) navEl.textContent = services.length + ' services';
  } else {
    document.getElementById('cards-container').innerHTML =
      '<div class="catalog-empty">No services in registry yet — be the first to register!</div>';
    // Set fallback stats
    ['stat-categories','stat-trust'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = '0';
    });
    // stat-services already set from /stats above; only reset if /stats also returned nothing
    statsPromise.then(data => {
      if (!data || (!data.total_services && !data.active_services)) {
        const el = document.getElementById('stat-services');
        if (el) el.textContent = '0';
      }
    });
  }

  renderGrid();
})();
</script>
</body>
</html>"""
