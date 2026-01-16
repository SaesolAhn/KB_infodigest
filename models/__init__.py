# Models module for InfoDigest Bot
# Contains data schemas for MongoDB documents

from .schemas import DigestLog, ContentType

__all__ = [
    "DigestLog",
    "ContentType",
]

