"""LangGraph saver adapter encrypting state, metadata and pending write values.

An encrypted serializer alone leaves SQLite/Postgres JSON metadata unprotected.
This adapter wraps each complete state and metadata before the installed saver
sees it, and strips non-routing configuration before persistence. Owner resolution
must use the session's immutable storage owner, not the caller's supplied owner.
"""

import base64
from collections.abc import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, get_checkpoint_metadata

from app.services.data_crypto import DataCrypto, DataDecryptionError

PAYLOAD_CHANNEL = "__huhua_secure_state__"
METADATA_FIELD = "__huhua_secure_metadata__"


class SecureCheckpointSaver(BaseCheckpointSaver):
    def __init__(self, inner, crypto: DataCrypto, owner_resolver: Callable[[str], str]):
        super().__init__()
        self.inner = inner
        self.crypto = crypto
        self.owner_resolver = owner_resolver

    @property
    def config_specs(self):
        return self.inner.config_specs

    def get_next_version(self, current, channel):
        return self.inner.get_next_version(current, channel)

    @staticmethod
    def _route(config):
        source = config["configurable"]
        route = {"thread_id": str(source["thread_id"]), "checkpoint_ns": source.get("checkpoint_ns", "")}
        if source.get("checkpoint_id"):
            route["checkpoint_id"] = source["checkpoint_id"]
        return {"configurable": route}

    def _context(self, config, checkpoint_id=None):
        route = config["configurable"]
        thread = str(route["thread_id"])
        owner = self.owner_resolver(thread)
        if not owner:
            raise DataDecryptionError("Checkpoint has no authorized storage owner")
        # Delimiters are represented as JSON, not ambiguous string joins.
        import json

        record = json.dumps([thread, route.get("checkpoint_ns", ""), checkpoint_id or route.get("checkpoint_id", "")], separators=(",", ":"))
        return {"owner": owner, "record": record}

    def _seal(self, value, *, field, **context):
        kind, encoded = self.serde.dumps_typed(value)
        return self.crypto.encrypt_json({"type": kind, "data": base64.b64encode(encoded).decode()}, field=field, **context)

    def _open(self, value, *, field, **context):
        blob = self.crypto.decrypt_json(value, field=field, **context)
        try:
            return self.serde.loads_typed((blob["type"], base64.b64decode(blob["data"], validate=True)))
        except (KeyError, TypeError, ValueError) as exc:
            raise DataDecryptionError("Invalid checkpoint serialization") from exc

    def _sealed_checkpoint(self, config, checkpoint, metadata):
        context = self._context(config, checkpoint["id"])
        envelope = self._seal(checkpoint, field="checkpoint", **context)
        # These outer fields are LangGraph routing/version bookkeeping only.
        # State including dynamic channel names stays inside the ciphertext.
        wrapped = {
            "v": 4, "id": checkpoint["id"], "ts": checkpoint["ts"],
            "channel_values": {PAYLOAD_CHANNEL: envelope},
            "channel_versions": {PAYLOAD_CHANNEL: checkpoint["id"]},
            "versions_seen": {}, "updated_channels": [PAYLOAD_CHANNEL],
        }
        wrapped_metadata = {METADATA_FIELD: self._seal(get_checkpoint_metadata(config, metadata), field="metadata", **context)}
        return wrapped, wrapped_metadata, {PAYLOAD_CHANNEL: checkpoint["id"]}

    def _unseal_tuple(self, value):
        if value is None or not self.crypto.enabled:
            return value
        context = self._context(value.config, value.checkpoint["id"])
        envelope = value.checkpoint.get("channel_values", {}).get(PAYLOAD_CHANNEL)
        metadata = value.metadata.get(METADATA_FIELD)
        if envelope is None or metadata is None:
            raise DataDecryptionError("Plaintext checkpoints require an explicit offline migration")
        checkpoint = self._open(envelope, field="checkpoint", **context)
        result_metadata = self._open(metadata, field="metadata", **context)
        writes = [(task_id, channel, self._open(data, field=f"write:{task_id}:{channel}", **context))
                  for task_id, channel, data in (value.pending_writes or [])]
        return CheckpointTuple(value.config, checkpoint, result_metadata, value.parent_config, writes)

    def get_tuple(self, config):
        return self._unseal_tuple(self.inner.get_tuple(self._route(config)))

    async def aget_tuple(self, config):
        return self._unseal_tuple(await self.inner.aget_tuple(self._route(config)))

    def put(self, config, checkpoint, metadata, new_versions):
        if not self.crypto.enabled:
            return self.inner.put(config, checkpoint, metadata, new_versions)
        wrapped, wrapped_metadata, versions = self._sealed_checkpoint(config, checkpoint, metadata)
        return self.inner.put(self._route(config), wrapped, wrapped_metadata, versions)

    async def aput(self, config, checkpoint, metadata, new_versions):
        if not self.crypto.enabled:
            return await self.inner.aput(config, checkpoint, metadata, new_versions)
        wrapped, wrapped_metadata, versions = self._sealed_checkpoint(config, checkpoint, metadata)
        return await self.inner.aput(self._route(config), wrapped, wrapped_metadata, versions)

    def _sealed_writes(self, config, writes, task_id):
        context = self._context(config)
        return [(channel, self._seal(value, field=f"write:{task_id}:{channel}", **context)) for channel, value in writes]

    def put_writes(self, config, writes, task_id, task_path=""):
        wrapped = self._sealed_writes(config, writes, task_id) if self.crypto.enabled else writes
        return self.inner.put_writes(self._route(config), wrapped, task_id, task_path)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        wrapped = self._sealed_writes(config, writes, task_id) if self.crypto.enabled else writes
        return await self.inner.aput_writes(self._route(config), wrapped, task_id, task_path)

    def list(self, config, *, filter=None, before=None, limit=None):
        if config is None:
            raise ValueError("Private checkpoints must be scoped to a thread")
        count = 0
        if limit is not None and limit <= 0:
            return
        for value in self.inner.list(self._route(config), before=self._route(before) if before else None):
            decoded = self._unseal_tuple(value)
            if filter and any(decoded.metadata.get(k) != v for k, v in filter.items()):
                continue
            yield decoded
            count += 1
            if limit is not None and count >= limit:
                break

    async def alist(self, config, *, filter=None, before=None, limit=None):
        if config is None:
            raise ValueError("Private checkpoints must be scoped to a thread")
        count = 0
        if limit is not None and limit <= 0:
            return
        async for value in self.inner.alist(self._route(config), before=self._route(before) if before else None):
            decoded = self._unseal_tuple(value)
            if filter and any(decoded.metadata.get(k) != v for k, v in filter.items()):
                continue
            yield decoded
            count += 1
            if limit is not None and count >= limit:
                break

    def delete_thread(self, thread_id):
        return self.inner.delete_thread(thread_id)

    async def adelete_thread(self, thread_id):
        return await self.inner.adelete_thread(thread_id)
