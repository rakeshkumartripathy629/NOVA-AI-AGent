"""
WebSocket endpoints.

* ``/ws/chat/{conversation_id}`` — authenticated streaming chat.
* ``/ws/notifications`` — real-time in-app notifications.
* ``/ws/agents/{execution_id}`` — agent execution progress.

All sockets authenticate with a bearer token passed as ``?token=...`` or
the ``Authorization`` query header (browser WebSocket limitation).
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import verify_token
from app.core.logging import get_logger

logger = get_logger("websocket")

router = APIRouter()

# connected clients: conversation_id -> set of websockets
_chat_clients: Dict[str, set] = {}
_notification_clients: Dict[str, set] = {}
_agent_clients: Dict[str, set] = {}


def _auth_websocket(websocket: WebSocket) -> Optional[UUID]:
    token = websocket.query_params.get("token")
    if not token:
        header = websocket.headers.get("authorization", "")
        if header.startswith("Bearer "):
            token = header[7:]
    if not token:
        return None
    try:
        token_data = verify_token(token, "access")
        return UUID(token_data.sub)
    except Exception:  # noqa: BLE001
        return None


async def broadcast(room: str, event: Dict[str, Any], clients: Dict[str, set]) -> None:
    """Send an event to every socket in a room."""
    payload = json.dumps(event)
    dead = []
    for socket in list(clients.get(room, set())):
        try:
            await socket.send_text(payload)
        except Exception:  # noqa: BLE001
            dead.append(socket)
    for socket in dead:
        clients.get(room, set()).discard(socket)


async def send_to_user(user_id: UUID, event: Dict[str, Any]) -> None:
    """Broadcast a notification/event to all sockets of a user."""
    await broadcast(str(user_id), event, _notification_clients)


async def send_chat_event(conversation_id: UUID, event: Dict[str, Any]) -> None:
    """Broadcast a chat event to a conversation room."""
    await broadcast(str(conversation_id), event, _chat_clients)


async def send_agent_event(execution_id: UUID, event: Dict[str, Any]) -> None:
    """Broadcast an agent execution event."""
    await broadcast(str(execution_id), event, _agent_clients)


@router.websocket("/ws/chat/{conversation_id}")
async def ws_chat(websocket: WebSocket, conversation_id: UUID):
    user_id = _auth_websocket(websocket)
    if user_id is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    room = str(conversation_id)
    _chat_clients.setdefault(room, set()).add(websocket)
    await websocket.send_text(
        json.dumps({"type": "connected", "conversation_id": conversation_id})
    )
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps({"type": "error", "message": "Invalid JSON"})
                )
                continue
            # Ping/pong heartbeat
            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            else:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "ack",
                            "id": message.get("id"),
                            "received": True,
                        }
                    )
                )
    except WebSocketDisconnect:
        _chat_clients.get(room, set()).discard(websocket)
    except Exception:  # noqa: BLE001
        logger.exception("Chat websocket error")
        _chat_clients.get(room, set()).discard(websocket)


@router.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket):
    user_id = _auth_websocket(websocket)
    if user_id is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    room = str(user_id)
    _notification_clients.setdefault(room, set()).add(websocket)
    await websocket.send_text(json.dumps({"type": "connected"}))
    try:
        while True:
            data = await websocket.receive_text()
            if json.loads(data).get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        _notification_clients.get(room, set()).discard(websocket)
    except Exception:  # noqa: BLE001
        _notification_clients.get(room, set()).discard(websocket)


@router.websocket("/ws/agents/{execution_id}")
async def ws_agents(websocket: WebSocket, execution_id: UUID):
    user_id = _auth_websocket(websocket)
    if user_id is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    room = str(execution_id)
    _agent_clients.setdefault(room, set()).add(websocket)
    await websocket.send_text(json.dumps({"type": "connected", "execution_id": str(execution_id)}))
    try:
        while True:
            data = await websocket.receive_text()
            if json.loads(data).get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        _agent_clients.get(room, set()).discard(websocket)
    except Exception:  # noqa: BLE001
        _agent_clients.get(room, set()).discard(websocket)
