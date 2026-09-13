"""Foundational tool registry contracts. No AI execution is implemented yet."""

from dataclasses import dataclass
from typing import Callable, Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: int
    risk: str
    handler: Callable[..., Any]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        if spec.risk not in {"read", "low", "medium", "high"}:
            raise ValueError(f"Invalid risk level: {spec.risk}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))
