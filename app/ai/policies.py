"""Synthetic policy library and a small retriever (the "R" in RAG).

Keyword overlap stands in for embeddings + a vector database (e.g. pgvector) so the
project runs offline. The interface, search_policy(query) -> documents, stays the same.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDocument:
    document_id: str
    version: int
    title: str
    text: str


POLICIES: tuple[PolicyDocument, ...] = (
    PolicyDocument(
        "policy-timeouts-v2", 2, "Gateway timeout handling",
        "When a gateway timeout occurs the final payment status may be unknown. "
        "Verify the final status with the processor before any retry. "
        "Never initiate a second charge while the status is unknown.",
    ),
    PolicyDocument(
        "policy-unmapped-codes-v1", 1, "Unknown or unmapped response codes",
        "An unknown response code with no approved rule must be investigated manually. "
        "Preserve the raw code, contact the merchant for context and propose a mapping for rule review.",
    ),
    PolicyDocument(
        "policy-risk-v1", 1, "Risk flag handling",
        "Any transaction with a risk flag goes to a risk reviewer. Automation must not act on it.",
    ),
)

_WORD = re.compile(r"[a-z]+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def search_policy(query: str, limit: int = 2) -> list[PolicyDocument]:
    query_words = _words(query)
    scored = [(len(query_words & _words(doc.title + " " + doc.text)), doc) for doc in POLICIES]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [doc for _, doc in scored[:limit]]
