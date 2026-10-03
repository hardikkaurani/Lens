"""Storage module exposing object storage abstraction and error classes."""

from app.storage.client import (
    ObjectNotFoundError,
    StorageClient,
    StorageConnectionError,
    StorageError,
    StorageObjectMeta,
    get_storage_client,
)

__all__ = [
    "ObjectNotFoundError",
    "StorageClient",
    "StorageConnectionError",
    "StorageError",
    "StorageObjectMeta",
    "get_storage_client",
]
