"""Small stateful DSL facade for context-efficient CadFlow agents.

The package is intentionally isolated from CadFlow's implementation.  It
compiles a restricted line-oriented language to the existing public
``cadflow`` API and stores only replayable command history between revisions.
"""

from .metrics import (
    CompressionReport,
    ConversationCompressionReport,
    ConversationTotals,
    compare_conversations,
    estimate_tokens,
    measure_compression,
    measure_conversation,
)
from .collaboration import (
    AgentProposal,
    CollaborationMessage,
    MergeConflict,
    MergeResponse,
    MultiAgentStore,
)
from .llm import (
    CodexCLIProvider,
    CodexNativeSubagentProvider,
    LLMError,
    LLMProvider,
    LLMProviderPool,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    NativeSubagentAudit,
    NativeSubagentRun,
    OpenAICompatibleProvider,
    audit_native_subagents,
)
from .orchestration import (
    AgentRun,
    AgentTask,
    CADFLOW_DSL_SYSTEM_PROMPT,
    DAGExecutionError,
    DAGExecutor,
    DAGRunReport,
    extract_dsl_document,
)
from .parser import DSLParseError, Instruction, parse
from .runtime import AgentModel, DSLExecutionError, DSLResponse
from .store import ModelStore

_REALTIME_EXPORTS = {
    "PreviewArtifact",
    "PreviewArtifactStore",
    "PreviewEvent",
    "PreviewEventHub",
    "PreviewHTTPServer",
    "RealtimePreview",
    "make_server",
}


def __getattr__(name: str):
    if name in _REALTIME_EXPORTS:
        from . import realtime

        return getattr(realtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AgentModel",
    "AgentProposal",
    "AgentRun",
    "AgentTask",
    "CADFLOW_DSL_SYSTEM_PROMPT",
    "CollaborationMessage",
    "CompressionReport",
    "ConversationCompressionReport",
    "ConversationTotals",
    "DSLExecutionError",
    "DSLParseError",
    "DSLResponse",
    "DAGExecutionError",
    "DAGExecutor",
    "DAGRunReport",
    "Instruction",
    "MergeConflict",
    "MergeResponse",
    "ModelStore",
    "MultiAgentStore",
    "CodexCLIProvider",
    "CodexNativeSubagentProvider",
    "LLMError",
    "LLMProvider",
    "LLMProviderPool",
    "LLMRequest",
    "LLMResponse",
    "LLMUsage",
    "NativeSubagentAudit",
    "NativeSubagentRun",
    "OpenAICompatibleProvider",
    "PreviewArtifact",
    "PreviewArtifactStore",
    "PreviewEvent",
    "PreviewEventHub",
    "PreviewHTTPServer",
    "RealtimePreview",
    "audit_native_subagents",
    "compare_conversations",
    "estimate_tokens",
    "extract_dsl_document",
    "measure_compression",
    "measure_conversation",
    "make_server",
    "parse",
]
