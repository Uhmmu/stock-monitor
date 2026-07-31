from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import get_current_user
from app.config import get_settings
from app.research.router import gateway
from app.research.service import ResearchGateway

from .exceptions import ToolError
from .executor import ToolExecutor
from .registry import tool_registry
from .schemas import (
    ToolBatchRequest,
    ToolCallRequest,
    ToolExecutionContext,
    ToolExecutionResult,
)

router = APIRouter(prefix="/api/ai-tools/v1", tags=["ai-tool-adapter"], dependencies=[Depends(get_current_user)])


def _enabled(*, batch: bool = False):
    settings=get_settings()
    if not settings.ai_tools_enabled or not settings.ai_tools_debug_api_enabled or (batch and not settings.ai_tools_batch_api_enabled):
        raise HTTPException(404,"AI tool debug API is disabled")


def _context(request: Request, user: Any) -> ToolExecutionContext:
    return ToolExecutionContext(request_id=request.headers.get("X-Request-ID") or str(uuid4()),user_id=user.id,caller="debug_api",
        max_tool_calls=max(1,min(get_settings().ai_tools_max_calls_per_batch,12)),max_parallel_calls=max(1,min(get_settings().ai_tools_max_parallel_calls,8)))


@router.get("/tools")
def list_tools(domain: str | None = Query(None,max_length=32), enabled_only: bool = True, include_schema: bool = False):
    _enabled(); definitions=tool_registry.list(domain=domain,enabled_only=enabled_only)
    values=[]
    for definition in definitions:
        row=definition.model_dump(mode="json")
        if not include_schema: row.pop("input_schema",None); row.pop("output_schema",None)
        values.append(row)
    return {"tools":values,"count":len(values),"read_only":True}


@router.get("/tools/{tool_name}")
def tool_detail(tool_name: str):
    _enabled()
    try: return tool_registry.get(tool_name).definition.model_dump(mode="json")
    except ToolError: raise HTTPException(404,"Tool not found") from None


@router.post("/execute",response_model=ToolExecutionResult)
async def execute_tool(body: ToolCallRequest, request: Request, user: Any = Depends(get_current_user), gw: ResearchGateway = Depends(gateway)):
    _enabled(); return await ToolExecutor(tool_registry,gw).execute(tool_name=body.tool,raw_arguments=body.arguments,context=_context(request,user))


@router.post("/execute-batch",response_model=list[ToolExecutionResult])
async def execute_batch(body: ToolBatchRequest, request: Request, user: Any = Depends(get_current_user), gw: ResearchGateway = Depends(gateway)):
    _enabled(batch=True)
    if len(body.calls)>8: raise HTTPException(422,"Debug batches are limited to 8 calls")
    return await ToolExecutor(tool_registry,gw).execute_many(body.calls,_context(request,user))


@router.get("/openai-schema")
def openai_schema(domain: str | None = Query(None,max_length=32), tools: list[str] = Query(default=[])):
    _enabled(); allowed=set(tools) if tools else None
    return {"tools":tool_registry.export_openai_tools(allowed_tools=allowed,domain=domain),"schema_only":True,"model_called":False}
