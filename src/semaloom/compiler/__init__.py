"""Shared compiler. Depends only on protocol-neutral core contracts."""

from semaloom.compiler.api import CompileResult, compile_documents, compile_paths
from semaloom.compiler.schema import document_schemas

__all__ = [
    "CompileResult",
    "compile_documents",
    "compile_paths",
    "document_schemas",
]
