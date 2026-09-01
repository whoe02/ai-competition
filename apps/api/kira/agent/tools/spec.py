"""The one contract every module uses to expose capability to the Butler.

A module makes itself controllable by declaring `ToolSpec`s and registering
them. The graph, the guard, the approval flow and the API never learn the
module's name — which is what makes "controls every module, present and
future" a structural property rather than a promise.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import User
from kira.engine.types import Snapshot
from kira.money import Money
from kira.services.dashboard import DashboardToday

ToolKind = Literal["read", "write", "workflow"]

_NAME = re.compile(r"^[a-z][a-z0-9_]{2,48}$")


def money_str(amount: Money) -> str:
    """Format for a human reading an evidence row, not for a machine."""
    if amount.currency == "MYR":
        return f"RM{amount.ringgit_str()}"
    return str(amount)


@dataclass(frozen=True, slots=True)
class EvidenceRow:
    """One line of "What I used". A label and an already-formatted value."""

    label: str
    value: str

    def as_pair(self) -> list[str]:
        return [self.label, self.value]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a handler returns: a value for the model, and evidence for the user."""

    value: Any
    evidence: tuple[EvidenceRow, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentReport:
    """What a sub-agent hands back: the same shape as a tool, plus its prose.

    `findings` is what the Butler reasons over and is delivered to it as an
    ordinary ToolMessage, so the reasoning loop cannot tell a specialist from a
    tool -- which is the whole of why adding an agent changes no node.

    `evidence` is already formatted for the panel, and is also the only thing
    the Butler is allowed to quote: a name or a figure that is not on one of
    these rows is one it invented. `answer` is the child's own sentence, kept
    for the two cases where the Butler will not be composing -- an approval
    card raised mid-turn, and the offline rung, where there is no composer
    worth the name.
    """

    findings: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceRow, ...] = ()
    answer: str = ""
    approval: dict[str, Any] | None = None
    llm_calls: int = 0


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything a handler is allowed to assume.

    The clock and the owning user are supplied, never fetched: a tool cannot
    read a different user's rows by accident, and cannot disagree with the
    rest of the app about what day it is.
    """

    session: AsyncSession
    user: User
    today: date
    snapshot: Snapshot
    dashboard: DashboardToday
    # A receipt or voice capture the user attached to this turn, if any. Tools
    # read it; they never fetch it, and it is a proposal until confirmed.
    attachment: dict[str, Any] | None = None

    @property
    def currency(self) -> str:
        return self.user.currency


@dataclass(frozen=True, slots=True)
class AgentContext:
    """A ToolContext, plus the run-scoped handles only an agent needs.

    A deterministic handler is given the session, the user and the clock and
    nothing else, on purpose. A child that runs its own model needs three more
    things -- somewhere to check point against, a model factory a test can
    swap, and a way to put its own progress on the parent's stream -- and they
    are here rather than on ToolContext so that a plain tool still cannot reach
    for a model.
    """

    tools: ToolContext
    thread_id: uuid.UUID
    request_id: uuid.UUID
    model_factory: Callable[..., Any] | None = None
    # emit(event_type, **data). A no-op when nobody is streaming.
    emit: Callable[..., None] = lambda *_, **__: None

    @property
    def session(self):
        return self.tools.session

    @property
    def user(self):
        return self.tools.user

    @property
    def today(self) -> date:
        return self.tools.today

    @property
    def currency(self) -> str:
        return self.tools.currency


Handler = Callable[[ToolContext, Any], Awaitable[ToolResult]]
AgentRunner = Callable[[AgentContext, Any], Awaitable[AgentReport]]
Summariser = Callable[[Any], str]


class ToolSpecError(ValueError):
    """A tool declaration that must not be allowed to reach the registry."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    module: str
    kind: ToolKind
    description: str
    args_model: type[BaseModel]
    handler: Handler
    # Required for writes: the sentence the user approves. A write with no
    # human-readable summary would be a silent write.
    summarise: Summariser | None = None
    # Shown in the stream while the tool runs, e.g. "Reading your ledger".
    label: str = ""
    # Required for workflows: the sub-agent that runs the call. A workflow is
    # exactly a capability with a model behind it, so the field that names that
    # model's entry point is the field that makes the kind mean anything.
    agent: AgentRunner | None = None

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise ToolSpecError(f"tool name {self.name!r} is not a lower_snake_case identifier")
        if self.kind not in ("read", "write", "workflow"):
            raise ToolSpecError(f"tool {self.name} has unknown kind {self.kind!r}")
        if not issubclass(self.args_model, BaseModel):
            raise ToolSpecError(f"tool {self.name} needs a pydantic args_model")
        if not self.description.strip():
            raise ToolSpecError(f"tool {self.name} needs a description; the model reads it")
        if self.kind == "workflow" and self.agent is None:
            raise ToolSpecError(
                f"workflow tool {self.name} has no agent(); a workflow is a handoff to "
                "something that reasons, and one with nothing behind it would be "
                "routed out of the loop and never come back"
            )
        if self.kind != "workflow" and self.agent is not None:
            raise ToolSpecError(
                f"tool {self.name} is kind={self.kind!r} but declares an agent(); only "
                "a workflow is delegated, so this one would never be called"
            )
        if self.kind == "write" and self.summarise is None:
            raise ToolSpecError(
                f"write tool {self.name} has no summarise(); a write the user cannot "
                "read before approving must not be registrable"
            )

    @property
    def is_write(self) -> bool:
        return self.kind == "write"

    @property
    def is_workflow(self) -> bool:
        return self.kind == "workflow"

    def human_label(self) -> str:
        return self.label or self.name.replace("_", " ").capitalize()

    def json_schema(self) -> dict[str, Any]:
        """The OpenAI-shaped function schema bound to the chat model."""
        parameters = self.args_model.model_json_schema()
        parameters.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


@dataclass(slots=True)
class ToolRegistry:
    """Every capability the Butler has. Adding a module means adding to this."""

    _specs: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._specs:
            raise ToolSpecError(f"tool {spec.name} is already registered")
        self._specs[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(sorted(self._specs.values(), key=lambda spec: spec.name))

    def reads(self) -> tuple[ToolSpec, ...]:
        return tuple(spec for spec in self if spec.kind == "read")

    def writes(self) -> tuple[ToolSpec, ...]:
        return tuple(spec for spec in self if spec.kind == "write")

    def workflows(self) -> tuple[ToolSpec, ...]:
        return tuple(spec for spec in self if spec.kind == "workflow")

    def modules(self) -> tuple[str, ...]:
        return tuple(sorted({spec.module for spec in self}))

    def schemas(self) -> list[dict[str, Any]]:
        return [spec.json_schema() for spec in self]
