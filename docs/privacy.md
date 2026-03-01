# Privacy Policy

**x402 Service Discovery API**
**Last updated: March 1, 2026**

---

## Overview

The x402 Service Discovery API (`https://x402-discovery-api.onrender.com`) is an MCP (Model Context Protocol) server that helps AI agents discover and interact with services that support the x402 HTTP payment protocol. This policy explains what data is collected when you use the service and how it is handled.

---

## Data We Collect

We collect the minimum data necessary to operate the service:

- **Service URLs** — URLs submitted as parameters to MCP tool calls (e.g., `discover_services`, `get_service_health`, `check_payment_support`). These are used only to fulfill the request.
- **On-chain payment records** — When a tool requires a micropayment (USDC on Base), the payment is processed entirely on the Base blockchain. We do not store your wallet address, private key, or payment authorization details. The on-chain transaction is public by the nature of the blockchain; we do not record it separately.

**We do not collect:**
- Names, email addresses, or any other personal information
- IP addresses or device identifiers
- Authentication credentials (most tools require no authentication)
- Browsing history or usage profiles

---

## How We Use Data

Data submitted through tool parameters is used solely to:

1. Look up or register service entries in the discovery registry
2. Return health, trust, and compatibility information about the requested service
3. Serve the response to the requesting agent or client

No submitted data is used for advertising, analytics profiling, or any purpose beyond completing the immediate API request.

---

## Third Parties

We do not sell, rent, or share any data with third parties. The service does not integrate third-party analytics, advertising, or tracking SDKs.

The only external system involved in payments is the **Base blockchain** (a public, decentralized network). Payment transactions submitted to that network are permanently public per blockchain design; this is outside our control.

---

## Retention

- **Service registry entries** are stored on the server for as long as the service is listed. Entries may be removed upon request.
- **Tool call inputs** (service URLs, query parameters) are not logged to persistent storage and are discarded after the response is sent.
- **Payment data** is not stored by this service; the on-chain record is maintained by the Base network.

---

## Contact

For questions, data removal requests, or any privacy concerns, contact us at:

**x402scout@proton.me**

We will respond to all inquiries within a reasonable timeframe.
