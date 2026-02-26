"""
agentkit-x402-discovery — Coinbase AgentKit ActionProvider for x402 Service Discovery.

Gives AgentKit agents the ability to discover and call x402-payable APIs at runtime.
The agent already has a funded Base wallet via AgentKit — this bridges it to the
x402 service ecosystem.

Install: pip install agentkit-x402-discovery
"""

from .provider import X402DiscoveryActionProvider, x402_discovery_action_provider

__all__ = ["X402DiscoveryActionProvider", "x402_discovery_action_provider"]
__version__ = "1.0.0"
