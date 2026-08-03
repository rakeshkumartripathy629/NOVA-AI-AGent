"""
Minimal workflow execution engine.

Executes a directed acyclic graph of steps (nodes + edges) defined in
``Workflow.definition``. Supports agent, llm, web_search, code, condition,
delay, email and output node types.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.ai.rag import retrieve
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("ai.workflow_engine")

SUPPORTED_TYPES = {"agent", "llm", "web_search", "code", "condition", "delay", "email", "output", "note"}


class WorkflowEngineError(Exception):
    """Raised when a workflow cannot be executed."""


def _topological_order(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[str]:
    """Return node ids in topological order; raises on cycles."""
    from_node = defaultdict(list)
    in_degree: Dict[str, int] = {n["id"]: 0 for n in nodes}
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source in in_degree and target in in_degree:
            from_node[source].append(target)
            in_degree[target] += 1

    queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
    ordered: List[str] = []
    while queue:
        nid = queue.popleft()
        ordered.append(nid)
        for next_id in from_node[nid]:
            in_degree[next_id] -= 1
            if in_degree[next_id] == 0:
                queue.append(next_id)

    if len(ordered) != len(in_degree):
        raise WorkflowEngineError("Workflow graph contains a cycle")
    return ordered


async def _run_node(
    node: Dict[str, Any],
    context: Dict[str, Any],
    node_outputs: Dict[str, Any],
) -> Any:
    """Execute a single node and return its result."""
    node_type = node.get("type", "note")
    data = node.get("data", {})
    inputs: Dict[str, Any] = {}

    for key, value in (data.get("inputs") or {}).items():
        if isinstance(value, str) and value.startswith("{{"):
            ref = value[2:-2].strip()
            node_id, _, field = ref.partition(".")
            source = node_outputs.get(node_id)
            inputs[key] = (source or {}).get(field) if field else source
        else:
            inputs[key] = value

    if node_type == "llm":
        from app.ai.providers import default_provider

        provider = default_provider()
        messages = [{"role": "user", "content": inputs.get("prompt", data.get("prompt", ""))}]
        if context.get("system_prompt"):
            system = context["system_prompt"]
        else:
            system = data.get("system_prompt")

        buffer: List[str] = []
        async for event in provider.stream(messages, model=inputs.get("model") or data.get("model")):
            if event.get("type") == "content":
                buffer.append(event["content"])
        return {"type": "llm", "output": "".join(buffer)}

    if node_type == "agent":
        from app.ai.providers import default_provider

        provider = default_provider()
        prompt = inputs.get("prompt") or data.get("prompt") or inputs.get("input") or ""
        messages = [{"role": "user", "content": prompt}]
        buffer: List[str] = []
        async for event in provider.stream(messages):
            if event.get("type") == "content":
                buffer.append(event["content"])
        return {"type": "agent", "output": "".join(buffer)}

    if node_type == "web_search":
        from app.ai.websearch import web_search_augment

        context_text, citations = await web_search_augment(
            inputs.get("query") or data.get("query") or ""
        )
        return {"type": "web_search", "output": context_text, "citations": citations}

    if node_type == "code":
        code = data.get("code", "")
        scope = {"inputs": inputs, "context": context, "retrieve": retrieve}
        if code.startswith("await "):
            exec_globals = scope
            exec_globals["__builtins__"] = __builtins__  # noqa: A002
            exec(  # noqa: S102
                f"async def _workflow_fn():\n    return {code}\n",
                exec_globals,
            )
            return {"type": "code", "output": await exec_globals["_workflow_fn"]()}
        exec(  # noqa: S102
            f"def _workflow_fn(inputs, context):\n    {code or 'return inputs'}",
            scope,
        )
        return {"type": "code", "output": scope["_workflow_fn"](inputs, context)}

    if node_type == "condition":
        expression = data.get("expression", "")
        scope = {"inputs": inputs, "node_outputs": node_outputs}
        exec(  # noqa: S102
            f"def _cond(inputs, node_outputs):\n    return bool({expression or 'True'})",
            scope,
        )
        return {"type": "condition", "output": scope["_cond"](inputs, node_outputs)}

    if node_type == "delay":
        seconds = float(data.get("seconds", 0))
        await asyncio.sleep(seconds)
        return {"type": "delay", "output": None}

    if node_type == "email":
        from app.core.email import email_service

        email_service.send_email(
            to=inputs.get("to") or data.get("to") or "",
            subject=inputs.get("subject") or data.get("subject") or "Workflow notification",
            body_text=inputs.get("body") or data.get("body") or "",
        )
        return {"type": "email", "output": "sent"}

    if node_type == "output":
        return {"type": "output", "output": inputs or data}

    return {"type": node_type, "output": inputs or data}


async def execute_workflow(
    *,
    session_factory,
    workflow_id: UUID,
    execution_id: UUID,
    inputs: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute a workflow and return its aggregated output."""
    from datetime import datetime

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.workflow import Workflow, WorkflowExecution

    async with session_factory() as db:
        workflow = (
            await db.execute(
                select(Workflow)
                .where(Workflow.id == workflow_id)
                .options(selectinload(Workflow.executions))
            )
        ).scalar_one_or_none()
        if not workflow:
            raise WorkflowEngineError("Workflow not found")

        execution = (
            await db.execute(select(WorkflowExecution).where(WorkflowExecution.id == execution_id))
        ).scalar_one_or_none()
        if not execution:
            raise WorkflowEngineError("Execution not found")

        definition = workflow.definition or {}
        nodes = definition.get("nodes", [])
        edges = definition.get("edges", [])

    ordered_ids = _topological_order(nodes, edges)
    node_map = {n["id"]: n for n in nodes}
    node_outputs: Dict[str, Any] = {}
    context: Dict[str, Any] = {
        "workflow_id": str(workflow_id),
        "execution_id": str(execution_id),
        "input": inputs,
    }
    steps: List[Dict[str, Any]] = []

    for index, node_id in enumerate(ordered_ids, start=1):
        node = node_map[node_id]
        try:
            result = await _run_node(node, context, node_outputs)
            node_outputs[node_id] = result
            steps.append({"step": index, "node": node.get("name", node_id), "status": "completed"})
            logger.info("Workflow %s node %s completed", workflow_id, node_id)
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": index, "node": node.get("name", node_id), "status": "failed", "error": str(exc)})
            raise WorkflowEngineError(f"Node {node.get('name', node_id)} failed: {exc}") from exc

    async with session_factory() as db:
        execution = (
            await db.execute(select(WorkflowExecution).where(WorkflowExecution.id == execution_id))
        ).scalar_one_or_none()
        if execution:
            execution.steps = steps
            execution.current_step = len(steps)
            await db.commit()

        workflow = (
            await db.execute(select(Workflow).where(Workflow.id == workflow_id))
        ).scalar_one_or_none()
        if workflow:
            workflow.execution_count += 1
            workflow.last_executed_at = datetime.utcnow()
            await db.commit()

    return {"steps": steps, "outputs": node_outputs, "final": node_outputs.get("final", {})}
