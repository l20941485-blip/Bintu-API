"""User-facing Bintu assistant MCP tool.

Routes validated extraction and knowledge operations to their dedicated
backend services. Extraction remains a public-web capability; knowledge
operations are scoped to the authenticated Supabase user.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bintu_api.mcp.schemas import TOOL_NAME
from bintu_api.rag.answer import RagAnswerService
from bintu_api.rag.retrieval import RagRetrievalService
from bintu_api.rag.supabase_retrieval import SupabaseRetrievalRepository
from bintu_api.security.auth import verify_supabase_user
from bintu_api.settings import Settings

ASSISTANT_TOOL_NAME = "bintu_assistant"
ASSISTANT_TOOL_TITLE = "Bintu Assistant"

ASSISTANT_TOOL_DESCRIPTION = (
    "Use Bintu to scrape a public web page or ask a question against a "
    "document in the signed-in user's knowledge base. Use domain=extraction "
    "for public scraping. Use domain=knowledge with action=ask_knowledge to "
    "answer a question from one user-owned document."
)

ASSISTANT_TOOL_ANNOTATIONS = {
    "title": ASSISTANT_TOOL_TITLE,
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}


class AssistantArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["extraction", "knowledge"]
    action: Literal[
        "scrape",
        "ask_knowledge",
    ]
    url: str | None = None
    query: str | None = None
    document_id: str | None = None
    max_tokens: int = Field(default=6000, ge=100, le=50000)
    limit: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def _validate_action(self) -> AssistantArguments:
        if self.domain == "extraction":
            if self.action != "scrape":
                raise ValueError("extraction supports only action=scrape")
            if not self.url:
                raise ValueError("extraction/scrape requires url")

        if self.domain == "knowledge":
            if self.action != "ask_knowledge":
                raise ValueError(
                    "knowledge currently supports only action=ask_knowledge"
                )
            if not self.query:
                raise ValueError("ask_knowledge requires query")
            if not self.document_id:
                raise ValueError("ask_knowledge requires document_id")

        return self


ASSISTANT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {
            "type": "string",
            "enum": ["extraction", "knowledge"],
            "description": "The Bintu capability to use.",
        },
        "action": {
            "type": "string",
            "enum": ["scrape", "ask_knowledge"],
            "description": (
                "For extraction, use scrape. For knowledge, use ask_knowledge."
            ),
        },
        "url": {
            "type": "string",
            "description": "Required for extraction/scrape: an absolute public HTTP or HTTPS URL.",
        },
        "query": {
            "type": "string",
            "description": "Required for knowledge/ask_knowledge.",
        },
        "document_id": {
            "type": "string",
            "description": "Required for knowledge/ask_knowledge: the user-owned document to query.",
        },
        "max_tokens": {
            "type": "integer",
            "minimum": 100,
            "maximum": 50000,
            "default": 6000,
            "description": "Extraction token budget for extraction/scrape.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20,
            "default": 5,
            "description": "Maximum number of knowledge chunks considered for an answer.",
        },
    },
    "required": ["domain", "action"],
    "additionalProperties": False,
}


def assistant_tool_definition() -> dict[str, Any]:
    return {
        "name": ASSISTANT_TOOL_NAME,
        "title": ASSISTANT_TOOL_TITLE,
        "description": ASSISTANT_TOOL_DESCRIPTION,
        "inputSchema": ASSISTANT_INPUT_SCHEMA,
        "annotations": ASSISTANT_TOOL_ANNOTATIONS,
    }


def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False),
            }
        ],
        "structuredContent": payload,
        "isError": False,
    }


def _tool_error(code: str, message: str, hint: str = "") -> dict[str, Any]:
    text = f"{code}: {message}"
    if hint:
        text = f"{text} {hint}"
    return {
        "content": [
            {
                "type": "text",
                "text": text.strip(),
            }
        ],
        "isError": True,
    }


async def call_assistant_tool(
    request: Request,
    settings: Settings,
    request_id: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    raw_arguments = params.get("arguments") or {}
    if not isinstance(raw_arguments, dict):
        return _tool_error(
            "invalid_arguments",
            "Tool arguments must be an object.",
        )

    try:
        arguments = AssistantArguments.model_validate(raw_arguments)
    except ValueError as error:
        return _tool_error(
            "invalid_arguments",
            str(error),
            "Check the bintu_assistant input schema and retry.",
        )

    if arguments.domain == "extraction":
        scrape_params = dict(params)
        scrape_params["name"] = TOOL_NAME
        scrape_params["arguments"] = {
            "url": arguments.url,
            "mode": "scrape",
            "max_tokens": arguments.max_tokens,
        }
        from bintu_api.mcp.streamable import _tools_call_result

        return await _tools_call_result(
            request=request,
            settings=settings,
            request_id=request_id,
            params=scrape_params,
        )

    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        return _tool_error(
            "knowledge_core_unavailable",
            "The knowledge core is not configured.",
        )

    try:
        user_id = await verify_supabase_user(request, settings)
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {}
        return _tool_error(
            str(detail.get("code", "invalid_session")),
            str(detail.get("message", "A valid sign-in session is required.")),
        )

    repository = SupabaseRetrievalRepository(supabase_client)
    retrieval = RagRetrievalService(repository)
    answer_service = RagAnswerService(retrieval)

    answer = await answer_service.answer(
        query=arguments.query or "",
        limit=arguments.limit,
        owner_identity=user_id,
        document_id=arguments.document_id,
    )

    return _tool_result(
        {
            "domain": "knowledge",
            "action": "ask_knowledge",
            "document_id": arguments.document_id,
            "answer": answer.answer,
            "insufficient_evidence": answer.insufficient_evidence,
            "citations": [
                {
                    "chunk_id": citation.chunk_id,
                    "revision_id": citation.revision_id,
                    "document_id": citation.document_id,
                    "source_url": citation.source_url,
                    "final_url": citation.final_url,
                    "heading_path": list(citation.heading_path),
                }
                for citation in answer.citations
            ],
        }
    )
