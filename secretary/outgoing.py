"""Recipient-visible attribution enforced independently of the language model."""

from .config import settings

SIGNATURE = settings.assistant_signature or f"-{settings.owner_first_name}'s Assistant"


def attributed(text: str) -> str:
    body = text.rstrip()
    # Idempotent for reviewed drafts and retry paths.
    while body.endswith(SIGNATURE):
        body = body[:-len(SIGNATURE)].rstrip()
    suffix = " " + SIGNATURE
    # Reserve room for attribution, including messages containing emoji.
    budget = 4096 - len(suffix)
    encoded = body.encode('utf-16-le')
    if len(encoded) // 2 > budget:
        body = encoded[:(budget - 1) * 2].decode('utf-16-le', errors='ignore').rstrip() + '…'
    return body + suffix
