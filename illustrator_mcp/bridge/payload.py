"""Version 1 immutable, byte-addressed host payload transfer (OR09/OR10).

The descriptor is a separate bounded frame. No payload is parsed or exposed to
a tool until identities, length and SHA-256 over its exact UTF-8 bytes agree.
Legacy replies carry unknown integrity; they never acquire a synthetic pass.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

CAPABILITY = "payload-v1"
MAX_BYTES = 32 * 1024 * 1024
PAGE_BYTES = 12288
TTL_SECONDS = 120
MAX_DESCRIPTOR_BYTES = 4096


class PayloadError(ValueError):
    def __init__(self, code: str, reason: str, **observed: Any):
        self.code, self.reason, self.observed = code, reason, observed
        super().__init__(f"[{code}] {reason}; host execution is not established by delivery failure; do not replay")

    def response(self, expected: dict) -> dict:
        return {"error": str(self), "execution": "unknown", "jobId": expected["jobId"],
                "requestToken": expected["requestToken"],
                "integrity": {"status": "failed", "reason": self.reason, "code": self.code,
                              **self.observed}}


@dataclass
class PayloadReceiver:
    expected: dict
    started: float = field(default_factory=time.monotonic)
    descriptor: dict | None = None
    pages: dict[int, bytes] = field(default_factory=dict)
    failure: PayloadError | None = None

    def expire(self):
        self.pages.clear()
        self.failure = self.failure or PayloadError("C015", "payload_expired")

    def _alive(self):
        if time.monotonic() - self.started >= TTL_SECONDS:
            self.expire()
            raise PayloadError("C015", "payload_expired")

    def describe(self, descriptor: Any):
        self._alive()
        if not isinstance(descriptor, dict) or len(json.dumps(descriptor).encode("utf-8")) > MAX_DESCRIPTOR_BYTES:
            raise PayloadError("C014", "invalid_descriptor")
        required = {"version", "jobId", "requestId", "requestToken", "sessionId", "hostSession",
                    "documentId", "payloadId", "encoding", "byteLength", "digestAlgorithm", "digest",
                    "transferMode", "pageBytes"}
        if set(descriptor) != required:
            raise PayloadError("C014", "invalid_descriptor_fields")
        if (descriptor["version"] != 1 or descriptor["encoding"] != "utf-8"
                or descriptor["digestAlgorithm"] != "sha256" or descriptor["transferMode"] != "pages"
                or descriptor["pageBytes"] != PAGE_BYTES):
            raise PayloadError("C014", "unsupported_descriptor")
        length = descriptor["byteLength"]
        if type(descriptor["requestId"]) is not int or descriptor["requestId"] < 1:
            raise PayloadError("C014", "invalid_request_identity")
        if type(length) is not int or not 0 <= length <= MAX_BYTES:
            raise PayloadError("C014", "payload_size_limit", declaredBytes=length)
        digest = descriptor["digest"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise PayloadError("C014", "invalid_digest")
        for name in ("jobId", "requestToken", "sessionId", "hostSession", "documentId", "payloadId"):
            if not isinstance(descriptor[name], str) or not descriptor[name] or len(descriptor[name]) > 256:
                raise PayloadError("C014", "invalid_identity", field=name)
        for name in ("jobId", "requestId", "requestToken", "sessionId", "payloadId", "hostSession", "documentId"):
            wanted = self.expected.get(name)
            if wanted is not None and descriptor[name] != wanted:
                raise PayloadError("C013", "identity_mismatch", field=name, expected=wanted, received=descriptor[name])
        if self.descriptor is not None and descriptor != self.descriptor:
            raise PayloadError("C013", "conflicting_descriptor")
        self.descriptor = dict(descriptor)

    def add_page(self, frame: dict):
        self._alive()
        if self.descriptor is None:
            raise PayloadError("C014", "missing_descriptor")
        if frame.get("payloadId") != self.descriptor["payloadId"]:
            raise PayloadError("C013", "identity_mismatch", field="payloadId")
        offset = frame.get("offset")
        if type(offset) is not int or offset < 0 or offset % PAGE_BYTES:
            raise PayloadError("C014", "invalid_page_offset")
        encoded = frame.get("data")
        if not isinstance(encoded, str) or len(encoded) > ((PAGE_BYTES + 2) // 3) * 4:
            raise PayloadError("C011", "overlong_page")
        try:
            block = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise PayloadError("C014", "invalid_page_encoding") from exc
        if offset + len(block) > self.descriptor["byteLength"]:
            raise PayloadError("C011", "overlong_payload")
        if offset in self.pages and self.pages[offset] != block:
            raise PayloadError("C012", "conflicting_duplicate_page", offset=offset)
        self.pages[offset] = block

    def finish(self) -> tuple[Any, dict]:
        self._alive()
        if self.failure:
            raise self.failure
        if self.descriptor is None:
            raise PayloadError("C014", "missing_descriptor")
        descriptor = self.descriptor
        blocks, received = [], 0
        for offset in range(0, descriptor["byteLength"], PAGE_BYTES):
            block = self.pages.get(offset, b"")
            expected_length = min(PAGE_BYTES, descriptor["byteLength"] - offset)
            if len(block) != expected_length:
                raise PayloadError("C010", "shorter_payload", expectedBytes=descriptor["byteLength"],
                                   receivedBytes=sum(map(len, self.pages.values())), offset=offset)
            blocks.append(block)
            received += len(block)
        raw = b"".join(blocks)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != descriptor["digest"]:
            raise PayloadError("C012", "digest_mismatch", expectedDigest=descriptor["digest"], receivedDigest=digest)
        try:
            payload = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, ValueError) as exc:
            # An intact payload can still be invalid JSON. Integrity is distinct
            # from parse validity, and this is never called truncation.
            raise PayloadError("C005", "verified_bytes_invalid_json", byteLength=received) from exc
        return payload, {"status": "verified", "descriptor": descriptor, "receivedBytes": received}
