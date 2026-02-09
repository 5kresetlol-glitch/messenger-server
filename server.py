import os
import json
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List, Dict

# --- ИСПОЛЬЗУЕМ СИНХРОННЫЕ ВЕРСИИ ---
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker

# --- 1. Настройка подключения к БД (без изменений) ---
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
    Column("recipient", String(255)), # <-- ДОБАВИЛИ ПОЛУЧАТЕЛЯ
    Column("text", String),
    Column("timestamp", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
)
metadata.create_all(bind=engine)

# --- 2. FastAPI и ConnectionManager ---
app = FastAPI()
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        # --- НОВОЕ: Рассылаем обновленный список пользователей ---
        await self.broadcast_user_list()

    async def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        # --- НОВОЕ: Рассылаем обновленный список пользователей ---
        await self.broadcast_user_list()

    async def broadcast(self, message: str):
        # ... (код без изменений)
        await asyncio.gather(*(conn.send_text(message) for conn in self.active_connections.values()))

    # --- НОВАЯ ФУНКЦИЯ: Разослать список пользователей ---
    async def broadcast_user_list(self):
        user_list = list(self.active_connections.keys())
        print(f"Рассылаю список пользователей: {user_list}")
        message = {
            "type": "user_list",
            "users": user_list
        }
        await self.broadcast(json.dumps(message))

manager = ConnectionManager()

# --- 3. Функции для работы с БД (пока не используются) ---
# ... (add_message_to_db_sync, get_message_history_sync)

# --- 4. WebSocket endpoint ---
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            # Пока просто держим соединение открытым
            data = await websocket.receive_text()
            print(f"Получено сообщение (пока игнорируется): {data}")

    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as e:
        print(f"Ошибка с клиентом {client_id}: {e}")
        await manager.disconnect(client_id)
