from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from app.research.service import ResearchGateway

from ..schemas import AdapterResult, ToolArguments, ToolDefinition, ToolExecutionContext

ArgsT = TypeVar("ArgsT", bound=ToolArguments)


class BaseToolAdapter(ABC, Generic[ArgsT]):
    definition: ToolDefinition
    arguments_model: type[ArgsT]

    @abstractmethod
    async def execute(self, args: ArgsT, context: ToolExecutionContext, gateway: ResearchGateway) -> AdapterResult:
        raise NotImplementedError

    def build_cache_key(self, args: ArgsT, context: ToolExecutionContext) -> str | None:
        if not self.definition.cache_ttl_seconds: return None
        payload = args.model_dump(mode="json", exclude_none=True)
        import hashlib
        import json
        scope = f"user:{context.user_id}" if self.definition.contains_private_data else "public"
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return f"ai-tool:v1:{scope}:{self.definition.name}:{self.definition.version}:{digest}"


def from_research(response, summary: str | None = None, partial: bool = False) -> AdapterResult:
    warning_codes={getattr(item,"code",None) for item in response.warnings}
    freshness_status=getattr(response.freshness,"status",None)
    partial=partial or bool(warning_codes & {"DATA_INCOMPLETE","SOURCE_STALE"}) or str(freshness_status) in {"stale","expired"}
    return AdapterResult(data=response.data, summary=summary, sources=response.sources,
                         freshness=response.freshness, warnings=response.warnings, partial=partial)
