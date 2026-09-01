"""The Butler's HTTP surface: the thread, the stream, approvals and memory.

The message endpoint streams because a turn takes several seconds and silence
is the wrong thing to show. It is a POST with a bearer header, which
`EventSource` cannot do, so the client reads the body with a stream reader.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.agent import events
from kira.agent.goal_graph.presentation import goal_evidence, goal_resume_answer
from kira.agent.goal_graph.run import resume_goal_run
from kira.agent.run import stream_resume, stream_turn
from kira.agent.scheduled_approvals import ScheduledApprovalError, apply_scheduled_approval
from kira.api.deps import CurrentUser, SessionDep, SessionFactory, StreamSessionDep
from kira.api.schemas import (
    ApprovalDecisionRequest,
    ButlerAskRequest,
    ButlerThreadResponse,
    MemoryCorrectionRequest,
    MemoryResponse,
)
from kira.db.models import APPROVAL_PENDING, ROLE_KIRA, ROLE_USER, User
from kira.services import butler_approvals, butler_memory, butler_thread
from kira.services.audit import ACTOR_USER, record
from kira.services.clock import today_for

router = APIRouter(prefix="/v1/butler", tags=["butler"])

NO_THREAD = HTTPException(status.HTTP_404_NOT_FOUND, "No such conversation")
NO_APPROVAL = HTTPException(status.HTTP_404_NOT_FOUND, "No such approval")
SETTLED = HTTPException(status.HTTP_409_CONFLICT, "That approval has already been decided")
NO_MEMORY = HTTPException(status.HTTP_404_NOT_FOUND, "No such memory")


async def _thread_payload(session: AsyncSession, user: User, thread) -> ButlerThreadResponse:
    history = await butler_thread.messages(session, thread)
    pending = await butler_approvals.pending_for(session, user)
    return ButlerThreadResponse(
        id=thread.id,
        title=thread.title,
        messages=[
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "evidence": [list(row) for row in message.evidence],
                "attachment": message.attachment,
                "created_at": message.created_at,
            }
            for message in history
        ],
        pending_approvals=[
            {
                "id": approval.id,
                "thread_id": approval.thread_id,
                "tool": approval.tool,
                "args": approval.args,
                "summary": approval.summary,
                "evidence": [list(row) for row in approval.evidence],
                "status": approval.status,
                "created_at": approval.created_at,
            }
            for approval in pending
            if approval.thread_id == thread.id
        ],
    )


@router.get("/thread", response_model=ButlerThreadResponse)
async def get_default_thread(user: CurrentUser, session: SessionDep) -> ButlerThreadResponse:
    """The user's conversation, created on first ask."""
    thread = await butler_thread.ensure_thread(session, user)
    await session.commit()
    return await _thread_payload(session, user, thread)


@router.get("/threads/{thread_id}", response_model=ButlerThreadResponse)
async def get_thread(
    thread_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ButlerThreadResponse:
    try:
        thread = await butler_thread.get_thread(session, user, thread_id)
    except butler_thread.ThreadNotFound as exc:
        raise NO_THREAD from exc
    return await _thread_payload(session, user, thread)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/threads/{thread_id}/messages")
async def post_message(
    thread_id: uuid.UUID,
    body: ButlerAskRequest,
    user: CurrentUser,
    session: SessionDep,
    factory: StreamSessionDep,
) -> StreamingResponse:
    try:
        await butler_thread.get_thread(session, user, thread_id)
    except butler_thread.ThreadNotFound as exc:
        raise NO_THREAD from exc
    return StreamingResponse(
        _run(factory, user.id, thread_id, body), media_type="text/event-stream"
    )


@router.post("/messages")
async def post_default_message(
    body: ButlerAskRequest,
    user: CurrentUser,
    session: SessionDep,
    factory: StreamSessionDep,
) -> StreamingResponse:
    """Ask without naming a thread. The client almost always wants this one."""
    thread = await butler_thread.ensure_thread(session, user)
    await session.commit()
    return StreamingResponse(
        _run(factory, user.id, thread.id, body), media_type="text/event-stream"
    )


async def _run(
    factory: SessionFactory,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    body: ButlerAskRequest,
) -> AsyncIterator[str]:
    async with factory() as session:
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one()
        thread = await butler_thread.get_thread(session, user, thread_id)
        today = today_for()

        asked = await butler_thread.append(
            session,
            user,
            thread,
            role=ROLE_USER,
            content=body.text,
            attachment=body.attachment,
        )
        await session.commit()
        yield _sse({"type": "message", "id": str(asked.id), "role": ROLE_USER})

        final: dict[str, Any] = {}
        async for event in stream_turn(
            session,
            user,
            thread,
            text=body.text,
            message_id=asked.id,
            today=today,
            attachment=body.attachment,
        ):
            if event.get("type") == events.DONE:
                final = event
            yield _sse(event)

        if final.get("answer"):
            await butler_thread.append(
                session,
                user,
                thread,
                role=ROLE_KIRA,
                content=final["answer"],
                evidence=final.get("evidence") or [],
                tool_calls=[{"name": name} for name in final.get("tools_used") or []],
            )
        await session.commit()


@router.post("/approvals/{approval_id}/respond")
async def respond(
    approval_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    user: CurrentUser,
    session: SessionDep,
    factory: StreamSessionDep,
) -> StreamingResponse:
    try:
        approval = await butler_approvals.get(session, user, approval_id)
    except butler_approvals.ApprovalNotFound as exc:
        raise NO_APPROVAL from exc
    if approval.status != APPROVAL_PENDING:
        raise SETTLED
    if approval.tool == "apply_goal_plan_change":
        if body.action == "edit" and body.args is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Goal plan edits require edited fields",
            )
        goal_decision = {
            "action": body.action,
            "edit": body.args if body.action == "edit" else None,
        }
        return StreamingResponse(
            _resume_goal(factory, user.id, approval.id, goal_decision),
            media_type="text/event-stream",
        )
    decision = {"action": body.action, "args": body.args or approval.args}
    return StreamingResponse(
        _resume(factory, user.id, approval.id, decision), media_type="text/event-stream"
    )


async def _resume_goal(
    factory: SessionFactory,
    user_id: uuid.UUID,
    approval_id: uuid.UUID,
    decision: dict[str, Any],
) -> AsyncIterator[str]:
    async with factory() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        approval = await butler_approvals.get(session, user, approval_id)
        thread = await butler_thread.get_thread(session, user, approval.thread_id)
        try:
            request_id = uuid.UUID(approval.graph_thread_id.rsplit(":", 1)[-1])
        except ValueError:
            yield _sse({"type": events.ERROR, "message": "Invalid goal graph checkpoint"})
            return
        result = await resume_goal_run(
            session,
            user,
            thread_id=approval.thread_id,
            request_id=request_id,
            decision=decision,
            as_of_date=today_for(),
            explain=False,
        )
        answer = goal_resume_answer(result, user.currency)
        evidence = goal_evidence(result.state, user.currency)
        if answer:
            yield _sse({"type": events.TOKEN, "text": answer})
        if evidence:
            yield _sse({"type": events.EVIDENCE, "rows": evidence})
        if result.approval is not None:
            yield _sse(
                {
                    "type": events.APPROVAL,
                    **result.approval,
                    "module": "goal_planning",
                    "args": {
                        "before": result.approval.get("before"),
                        "after": result.approval.get("after"),
                        "base_plan_version": result.approval.get("base_plan_version"),
                    },
                }
            )
        applied = None
        if (result.state.get("approval") or {}).get("status") == "applied":
            applied = {
                "tool": "apply_goal_plan_change",
                "summary": "The approved goal plan version was saved.",
            }
        yield _sse(
            {
                "type": events.DONE,
                "answer": answer,
                "evidence": evidence,
                "tools_used": ["start_goal_planning"],
                "request_id": str(result.request_id),
                "approval": result.approval or result.state.get("approval"),
                "applied": applied,
                "llm_calls": result.llm_calls,
            }
        )
        if answer:
            await butler_thread.append(
                session,
                user,
                thread,
                role=ROLE_KIRA,
                content=answer,
                evidence=evidence,
                tool_calls=[{"name": "start_goal_planning"}],
            )
        await session.commit()


async def _resume(
    factory: SessionFactory,
    user_id: uuid.UUID,
    approval_id: uuid.UUID,
    decision: dict[str, Any],
) -> AsyncIterator[str]:
    async with factory() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        approval = await butler_approvals.get(session, user, approval_id)
        thread = await butler_thread.get_thread(session, user, approval.thread_id)
        final: dict[str, Any] = {}
        if approval.graph_thread_id.startswith("briefing:"):
            if decision["action"] == "reject":
                await butler_approvals.settle(session, approval, applied=False)
                await record(
                    session,
                    user,
                    actor=ACTOR_USER,
                    action=f"butler.rejected.{approval.tool}",
                    detail={"summary": approval.summary},
                )
                final = {"answer": "Okay — I left that draft unchanged.", "evidence": []}
            else:
                try:
                    applied = await apply_scheduled_approval(
                        session,
                        user,
                        approval,
                        arguments=decision["args"],
                        today=today_for(),
                    )
                except ScheduledApprovalError as exc:
                    yield _sse({"type": events.ERROR, "message": str(exc)})
                    return
                final = {"answer": applied.answer, "evidence": applied.evidence}
            yield _sse({"type": events.DONE, **final})
        else:
            async for event in stream_resume(
                session,
                user,
                thread,
                graph_thread=approval.graph_thread_id,
                decision=decision,
                today=today_for(),
            ):
                if event.get("type") == events.DONE:
                    final = event
                yield _sse(event)

        # A rejection never reaches the approval node's settle path, so the
        # projection is closed here rather than left pending forever.
        if decision["action"] == "reject" and approval.status == APPROVAL_PENDING:
            await butler_approvals.settle(session, approval, applied=False)
            await record(
                session,
                user,
                actor=ACTOR_USER,
                action=f"butler.rejected.{approval.tool}",
                detail={"summary": approval.summary},
            )
        if final.get("answer"):
            await butler_thread.append(
                session,
                user,
                thread,
                role=ROLE_KIRA,
                content=final["answer"],
                evidence=final.get("evidence") or [],
            )
        await session.commit()


@router.get("/memories", response_model=list[MemoryResponse])
async def list_memories(user: CurrentUser, session: SessionDep) -> list[MemoryResponse]:
    """Everything Kira believes about this user, in the order it is retrieved."""
    memories = await butler_memory.list_memories(session, user)
    return [MemoryResponse.model_validate(memory) for memory in memories]


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
async def correct_memory(
    memory_id: uuid.UUID,
    body: MemoryCorrectionRequest,
    user: CurrentUser,
    session: SessionDep,
) -> MemoryResponse:
    try:
        memory = await butler_memory.correct(session, user, memory_id, body.fact)
    except butler_memory.MemoryNotFound as exc:
        raise NO_MEMORY from exc
    await record(
        session,
        user,
        actor=ACTOR_USER,
        action="butler.memory.corrected",
        detail={"memory_id": str(memory_id), "fact": memory.fact},
    )
    await session.commit()
    return MemoryResponse.model_validate(memory)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    try:
        memory = await butler_memory.forget(session, user, memory_id)
    except butler_memory.MemoryNotFound as exc:
        raise NO_MEMORY from exc
    await record(
        session,
        user,
        actor=ACTOR_USER,
        action="butler.memory.forgotten",
        detail={"memory_id": str(memory_id), "fact": memory.fact},
    )
    await session.commit()
