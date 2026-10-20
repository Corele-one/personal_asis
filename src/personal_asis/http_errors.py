"""Small shared HTTP validation primitives; independent of retired relay services."""
import hashlib


class ProtocolError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.status = status


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()
