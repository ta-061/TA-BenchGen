"""Every failure the tool distinguishes, in one place."""


class ValidationError(ValueError):
    """Untrusted candidate or persisted dataset does not satisfy the contract."""


class ExecutionError(RuntimeError):
    """Build, boot, transport or environment failure, not a TA result."""


class GenerationAPIError(ExecutionError):
    """Safe API diagnostics and whether another attempt can help unchanged.

    declined marks a provider content filter or refusal: it concerns this request only,
    so the request ends without a retry and the run continues with the next request.
    """

    def __init__(self, message, retryable=False, declined=False):
        super().__init__(message)
        self.retryable = retryable
        self.declined = declined


class JudgmentError(Exception):
    """A candidate did not pass machine validation; carries the measured evidence."""

    def __init__(self, status, reason, semantic=None):
        super().__init__(reason)
        self.status = status
        self.semantic = semantic or {}
