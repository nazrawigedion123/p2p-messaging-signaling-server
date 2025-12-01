# signal_server.py
import asyncio
import json
import uuid
from typing import Dict, Optional, List, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

app = FastAPI()

# ==========================================
# 1. Models (Replicating src/model.rs)
# ==========================================

class PeerInfo(BaseModel):
    peer_id: str
    username: str

class PeerState:
    def __init__(self, ws: WebSocket, username: Optional[str] = None):
        self.ws = ws
        self.username = username
        self.room: Optional[str] = None

# ==========================================
# 2. State Management (Replicating DashMap)
# ==========================================

class ConnectionManager:
    def __init__(self):
        # Equivalent to Arc<DashMap<String, PeerState>>
        self.peers: Dict[str, PeerState] = {}

    async def connect(self, peer_id: str, ws: WebSocket):
        await ws.accept()
        self.peers[peer_id] = PeerState(ws)
        print(f"{peer_id} connected, awaiting login")

    def disconnect(self, peer_id: str):
        if peer_id in self.peers:
            del self.peers[peer_id]
        print(f"{peer_id} disconnected")

    def get_peer(self, peer_id: str) -> Optional[PeerState]:
        return self.peers.get(peer_id)

    async def send_json(self, peer_id: str, message: dict):
        peer = self.peers.get(peer_id)
        if peer:
            try:
                await peer.ws.send_json(message)
            except RuntimeError:
                # Handle cases where connection might be closed mid-send
                pass

    async def broadcast_to_room(self, room: str, message: dict, exclude_peer_id: str):
        # We iterate over a copy of items to allow safe async operations
        for pid, state in list(self.peers.items()):
            if pid != exclude_peer_id and state.room == room:
                try:
                    await state.ws.send_json(message)
                except RuntimeError:
                    pass

manager = ConnectionManager()

# ==========================================
# 3. Message Logic (Replicating src/handler.rs)
# ==========================================

async def process_message(peer_id: str, msg_type: str, payload: Any):
    peer = manager.get_peer(peer_id)
    if not peer:
        return

    # Case: Login
    if msg_type == "Login":
        username = payload.get("username")
        peer.username = username
        print(f"{peer_id} logged in as {peer.username}")

    # Case: Join
    elif msg_type == "Join":
        new_room = payload.get("room")
        old_room = peer.room
        
        # Update state
        peer.room = new_room
        username = peer.username if peer.username else "Anonymous"

        # Notify old room if exists
        if old_room:
            await broadcast_peer_left(old_room, peer_id)

        # Notify new room
        await broadcast_peer_joined(new_room, peer_id, username)

        # Send existing peers list to the joiner
        existing_peers = []
        for pid, state in manager.peers.items():
            if pid != peer_id and state.room == new_room:
                existing_peers.append({
                    "peer_id": pid,
                    "username": state.username or "Anonymous"
                })
        
        await manager.send_json(peer_id, {
            "type": "ExistingPeers",
            "payload": {"peers": existing_peers}
        })

    # Case: Signal
    elif msg_type == "Signal":
        target = payload.get("target")
        data = payload.get("data")
        
        # Rust logic: Forward the signal to target, replacing 'target' field with sender's ID
        if target:
            await manager.send_json(target, {
                "type": "Signal",
                "payload": {
                    "target": peer_id, # The receiver needs to know who sent it
                    "data": data
                }
            })

async def broadcast_peer_joined(room: str, peer_id: str, username: str):
    await manager.broadcast_to_room(room, {
        "type": "PeerJoined",
        "payload": {
            "peer_id": peer_id,
            "username": username
        }
    }, exclude_peer_id=peer_id)

async def broadcast_peer_left(room: str, peer_id: str):
    await manager.broadcast_to_room(room, {
        "type": "PeerLeft",
        "payload": {
            "peer_id": peer_id
        }
    }, exclude_peer_id=peer_id)

# ==========================================
# 4. WebSocket Handler (Replicating main.rs)
# ==========================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    peer_id = str(uuid.uuid4())
    await manager.connect(peer_id, websocket)

    try:
        # Await first message (Login check)
        # Note: Rust handles this manually, here we just check the first msg in loop
        # or we can do a specific 'receive' once. Let's stick to the loop for simplicity
        # but enforce login logic inside the loop or via a flag.
        
        # In Rust, you specifically wait for 1 message to login. 
        # Here we will iterate, but if the user isn't logged in, we expect Login.
        
        while True:
            # Wait for message
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                print(f"Failed to parse message from {peer_id}")
                continue

            # Rust serde config: tag="type", content="payload"
            msg_type = message.get("type")
            payload = message.get("payload")

            peer = manager.get_peer(peer_id)
            
            # Enforce Login as first action (mirroring Rust logic)
            if peer and peer.username is None:
                if msg_type == "Login":
                    username = payload.get("username")
                    peer.username = username
                    print(f"{peer_id} logged in as {username}")
                    continue # Successfully logged in
                else:
                    print(f"{peer_id} first message was not login, disconnecting")
                    await websocket.close()
                    break

            # Normal processing
            await process_message(peer_id, msg_type, payload)

    except WebSocketDisconnect:
        print(f"{peer_id} disconnected")
    except Exception as e:
        print(f"Error for {peer_id}: {e}")
    finally:
        # Cleanup
        peer = manager.get_peer(peer_id)
        if peer and peer.room:
            await broadcast_peer_left(peer.room, peer_id)
        manager.disconnect(peer_id)

if __name__ == "__main__":
    import uvicorn
    print("Signaling server started on 0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)