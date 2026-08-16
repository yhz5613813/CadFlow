"""Dependency-free context size estimates for DSL experiments."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Sequence


_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|[^\w\s]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Estimate model tokens using a stable lexical proxy.

    The project does not require a tokenizer dependency.  This deliberately
    conservative proxy counts identifiers, numbers, and punctuation, and is
    used only for comparing two prompts, never for billing or API limits.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return len(_TOKEN.findall(text))


@dataclass(frozen=True)
class CompressionReport:
    verbose_tokens: int
    dsl_tokens: int

    @property
    def saved_tokens(self) -> int:
        return self.verbose_tokens - self.dsl_tokens

    @property
    def reduction_ratio(self) -> float:
        if self.verbose_tokens == 0:
            return 0.0
        return self.saved_tokens / self.verbose_tokens

    @property
    def meets_twenty_percent_target(self) -> bool:
        return self.reduction_ratio >= 0.20

    def to_dict(self) -> dict[str, object]:
        return {
            "verbose_tokens": self.verbose_tokens,
            "dsl_tokens": self.dsl_tokens,
            "saved_tokens": self.saved_tokens,
            "reduction_ratio": self.reduction_ratio,
            "meets_twenty_percent_target": self.meets_twenty_percent_target,
        }


def measure_compression(verbose_context: str, dsl_context: str) -> CompressionReport:
    return CompressionReport(estimate_tokens(verbose_context), estimate_tokens(dsl_context))


def _message(role: str, content: str) -> str:
    return f"<{role}>\n{content.strip()}\n</{role}>\n"


@dataclass(frozen=True)
class ConversationTotals:
    """Whole-session context totals for one request/response protocol."""

    turns: int
    request_tokens: int
    response_tokens: int
    final_window_tokens: int
    cumulative_input_tokens: int
    total_processed_tokens: int
    wire_bytes: int
    final_window_bytes: int
    cumulative_input_bytes: int
    total_processed_bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "turns": self.turns,
            "request_tokens": self.request_tokens,
            "response_tokens": self.response_tokens,
            "final_window_tokens": self.final_window_tokens,
            "cumulative_input_tokens": self.cumulative_input_tokens,
            "total_processed_tokens": self.total_processed_tokens,
            "wire_bytes": self.wire_bytes,
            "final_window_bytes": self.final_window_bytes,
            "cumulative_input_bytes": self.cumulative_input_bytes,
            "total_processed_bytes": self.total_processed_bytes,
        }


def measure_conversation(
    requests: Sequence[str],
    responses: Sequence[str],
    *,
    fixed_context: str = "",
    token_counter: Callable[[str], int] = estimate_tokens,
) -> ConversationTotals:
    """Measure a complete multi-turn protocol, including actual responses.

    ``cumulative_input`` sums the full input prefix presented at every turn.
    ``total_processed`` adds generated responses to that input total. The
    optional fixed context is included once per model input and once in the
    final retained window.
    """
    if len(requests) != len(responses):
        raise ValueError("requests and responses must contain the same turns")
    if not requests:
        raise ValueError("conversation must contain at least one turn")
    if any(not isinstance(item, str) for item in (*requests, *responses)):
        raise TypeError("conversation requests and responses must be strings")
    if not isinstance(fixed_context, str):
        raise TypeError("fixed_context must be a string")
    if not callable(token_counter):
        raise TypeError("token_counter must be callable")

    fixed = _message("system", fixed_context) if fixed_context else ""
    transcript = ""
    cumulative_input_tokens = 0
    cumulative_input_bytes = 0
    response_tokens = 0
    response_bytes = 0
    request_tokens = 0
    request_bytes = 0
    for request, response in zip(requests, responses):
        user_message = _message("user", request)
        assistant_message = _message("assistant", response)
        request_tokens += token_counter(user_message)
        request_bytes += len(user_message.encode("utf-8"))
        response_tokens += token_counter(assistant_message)
        response_bytes += len(assistant_message.encode("utf-8"))
        model_input = f"{fixed}{transcript}{user_message}"
        cumulative_input_tokens += token_counter(model_input)
        cumulative_input_bytes += len(model_input.encode("utf-8"))
        transcript += f"{user_message}{assistant_message}"

    final_window = f"{fixed}{transcript}"
    final_window_tokens = token_counter(final_window)
    final_window_bytes = len(final_window.encode("utf-8"))
    return ConversationTotals(
        turns=len(requests),
        request_tokens=request_tokens,
        response_tokens=response_tokens,
        final_window_tokens=final_window_tokens,
        cumulative_input_tokens=cumulative_input_tokens,
        total_processed_tokens=cumulative_input_tokens + response_tokens,
        wire_bytes=request_bytes + response_bytes,
        final_window_bytes=final_window_bytes,
        cumulative_input_bytes=cumulative_input_bytes,
        total_processed_bytes=cumulative_input_bytes + response_bytes,
    )


@dataclass(frozen=True)
class ConversationCompressionReport:
    """Absolute and relative whole-session savings between two protocols."""

    baseline: ConversationTotals
    dsl: ConversationTotals

    @staticmethod
    def _saved(baseline: int, dsl: int) -> int:
        return baseline - dsl

    @staticmethod
    def _ratio(baseline: int, dsl: int) -> float:
        return 0.0 if baseline == 0 else (baseline - dsl) / baseline

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline": self.baseline.to_dict(),
            "dsl": self.dsl.to_dict(),
            "savings": {
                "request_tokens": self._saved(
                    self.baseline.request_tokens, self.dsl.request_tokens
                ),
                "request_token_ratio": self._ratio(
                    self.baseline.request_tokens, self.dsl.request_tokens
                ),
                "final_window_tokens": self._saved(
                    self.baseline.final_window_tokens,
                    self.dsl.final_window_tokens,
                ),
                "final_window_token_ratio": self._ratio(
                    self.baseline.final_window_tokens,
                    self.dsl.final_window_tokens,
                ),
                "total_processed_tokens": self._saved(
                    self.baseline.total_processed_tokens,
                    self.dsl.total_processed_tokens,
                ),
                "total_processed_token_ratio": self._ratio(
                    self.baseline.total_processed_tokens,
                    self.dsl.total_processed_tokens,
                ),
                "wire_bytes": self._saved(
                    self.baseline.wire_bytes, self.dsl.wire_bytes
                ),
                "wire_byte_ratio": self._ratio(
                    self.baseline.wire_bytes, self.dsl.wire_bytes
                ),
                "final_window_bytes": self._saved(
                    self.baseline.final_window_bytes,
                    self.dsl.final_window_bytes,
                ),
                "final_window_byte_ratio": self._ratio(
                    self.baseline.final_window_bytes,
                    self.dsl.final_window_bytes,
                ),
                "total_processed_bytes": self._saved(
                    self.baseline.total_processed_bytes,
                    self.dsl.total_processed_bytes,
                ),
                "total_processed_byte_ratio": self._ratio(
                    self.baseline.total_processed_bytes,
                    self.dsl.total_processed_bytes,
                ),
            },
        }


def compare_conversations(
    baseline_requests: Sequence[str],
    dsl_requests: Sequence[str],
    *,
    baseline_responses: Sequence[str],
    dsl_responses: Sequence[str],
    fixed_context: str = "",
    token_counter: Callable[[str], int] = estimate_tokens,
) -> ConversationCompressionReport:
    """Compare complete baseline and DSL conversations using one metric."""
    return ConversationCompressionReport(
        measure_conversation(
            baseline_requests,
            baseline_responses,
            fixed_context=fixed_context,
            token_counter=token_counter,
        ),
        measure_conversation(
            dsl_requests,
            dsl_responses,
            fixed_context=fixed_context,
            token_counter=token_counter,
        ),
    )
