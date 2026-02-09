import os
import json
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List, Dict

# --- ИСПОЛЬЗУЕМ СИНХРОННЫЕ ВЕРСИИ ---
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker

# --- 1. Настройка подключения к БД (СИНХРОННЫЙ РЕЖИМ) ---
DB_USER = os.environ.get("DB_USER")
DB_PASS = os.environ.get("DB_PASS")
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_NAME = os.environ.get("DB_NAME")

if not all([DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME]):
    raise RuntimeError("Переменные для подключения к БД не установлены!")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

metadata = MetaData()
messages_table = Table(
    "messages", metadata,
    Column("id", Integer, primary_key=True),
    Column("sender", String(255)),
    Column("text", String),
    Column("timestamp", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
)

# Создаем таблицу при запуске, если ее нет
metadata.create_all(bind=engine)

# --- 2. FastAPI и ConnectionManager ---
app = FastAPI()
class ConnectionManager:
    def __init__(self): self.active_connections: Dict[str, WebSocket] = {};
    async def connect(self, ws, id): await ws.accept(); self.active_connections[id] = ws;
    def disconnect(self, id): self.active_connections.pop(id, None);
    async def broadcast(self, msg): await asyncio.gather(*(conn.send_text(msg) for conn in self.active_connections.values()));
    async def send_personal_message(self, msg, ws): await ws.send_text(msg);
manager = ConnectionManager()

# --- 3. СИНХРОННЫЕ функции для работы с БД ---
def add_message_to_db_sync(sender: str, text: str):
    db = SessionLocal()
    try:
        db.execute(messages_table.insert().values(sender=sender, text=text))
        db.commit()
        print(f"SYNC SAVE: Сообщение от {sender} сохранено.")
    except Exception as e:
        print(f"!!! SYNC DB ERROR: {e}")
        db.rollback()
    finally:
        db.close()

def get_message_history_sync(limit: int = 30) -> List[Dict]:
    db = SessionLocal()
    try:
        res = db.execute(messages_table.select().order_by(messages_table.c.timestamp.desc()).limit(limit))
        history = [dict(row) for row in res.mappings()]
        for msg in history: msg['timestamp'] = msg['timestamp'].isoformat()
        return history
    finally:
        db.close()

# --- 4. Основной WebSocket endpoint ---
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        history = await asyncio.to_thread(get_message_history_sync)
        for msg in history:
            await manager.send_personal_message(json.dumps(msg), websocket)
        
        await manager.broadcast(json.dumps({"sender": "Сервер", "text": f"{client_id} присоединился."}))
        
        while True:
            data = await websocket.receive_text()
            await asyncio.to_thread(add_message_to_db_sync, client_id, data)
            
            message_data = {"sender": client_id, "text": data}
            await manager.broadcast(json.dumps(message_data))
            
    except WebSocketDisconnect:
        manager.disconnect(client_id)
        await manager.broadcast(json.dumps({"sender": "Сервер", "text": f"{client_id} покинул чат."}))
    except Exception as e:
        print(f"!!! WEBSOCKET ERROR: {e}")
        manager.disconnect(client_id)

