class X402DiscoveryError(Exception):
    """Base exception for x402discovery."""


class PaymentRequired(X402DiscoveryError):
    """Raised when x402 payment is required but no payment header provided."""

    def __init__(self, payment_info: dict):
        self.payment_info = payment_info
        super().__init__(
            f"x402 payment required: {payment_info.get('amount', '?')} USDC"
            f" to {payment_info.get('payTo', '?')}"
        )


class ServiceNotFound(X402DiscoveryError):
    """Raised when no services match the query."""


class DiscoveryAPIError(X402DiscoveryError):
    """Raised when the discovery API returns an unexpected error."""
