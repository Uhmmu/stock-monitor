from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from .exceptions import BlockVersionError, UnknownBlockError
from .schemas import (
    BLOCK_DATA_MODELS,
    RichBlock,
    RichBlockDefinition,
)


class RichBlockRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, int], tuple[type[BaseModel], Any]] = {}

    def register(
        self,
        *,
        block_type: str,
        version: int,
        data_model: type[BaseModel],
        factory: Any | None = None,
    ) -> None:
        key = (block_type, version)
        if key in self._definitions:
            raise ValueError(f"duplicate rich block registration: {block_type}:{version}")
        schema = data_model.model_json_schema()
        json.dumps(schema, ensure_ascii=False)
        self._definitions[key] = (data_model, factory)

    def get_schema(self, block_type: str, version: int) -> type[BaseModel]:
        versions = [key for key in self._definitions if key[0] == block_type]
        if not versions:
            raise UnknownBlockError(f"unknown rich block type: {block_type}")
        try:
            return self._definitions[(block_type, version)][0]
        except KeyError as exc:
            raise BlockVersionError(
                f"unsupported rich block version: {block_type}:{version}"
            ) from exc

    def validate_block(self, block: RichBlock) -> RichBlock:
        model = self.get_schema(block.block_type, block.block_version)
        data = model.model_validate(block.data).model_dump(mode="json")
        json.dumps(data, ensure_ascii=False)
        return block.model_copy(update={"data": data})

    def list_supported(self) -> list[RichBlockDefinition]:
        return [
            RichBlockDefinition(
                block_type=block_type,
                version=version,
                data_schema=model.model_json_schema(),
            )
            for (block_type, version), (model, _) in sorted(
                self._definitions.items()
            )
        ]


def build_rich_block_registry() -> RichBlockRegistry:
    registry = RichBlockRegistry()
    for block_type, model in BLOCK_DATA_MODELS.items():
        registry.register(block_type=block_type, version=1, data_model=model)
    return registry


rich_block_registry = build_rich_block_registry()
