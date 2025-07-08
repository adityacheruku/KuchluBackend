from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from app.websocket.manager import manager
from datetime import datetime
import asyncio

router = APIRouter()

async def broadcast_presence_update(user_id: str, is_online: bool, last_seen: datetime = None):
    # TODO: Determine relevant contacts/chats to broadcast to
    await manager.broadcast(
        event="user_presence_update",
        data={
            "userId": user_id,
            "is_online": is_online,
            "last_seen": last_seen.isoformat() if last_seen else None
        }
    )

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(user_id, websocket)
    # Mark user as online and broadcast
    await broadcast_presence_update(user_id, True)
    try:
        while True:
            data = await websocket.receive_json()
            event = data.get("event")
            payload = data.get("data")
            # TODO: Handle events (send_message, toggle_reaction, update_typing_indicator, etc.)
            # Example:
            # if event == "send_message":
            #     ...
            # Periodically update last_seen (placeholder, not production-ready)
            # await asyncio.sleep(60)
            # await broadcast_presence_update(user_id, True, datetime.utcnow())
    except WebSocketDisconnect:
        manager.disconnect(user_id)
        # Mark user as offline and broadcast
        await broadcast_presence_update(user_id, False, datetime.utcnow()) 