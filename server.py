import os
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List

from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String, DateTime
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# --- УДАЛЯЕМ СОЗДАНИЕ ENGINE И SESSION ОТСЮДА ---

# "Описываем" нашу таблицу для сообщений
metadata = MetaData()
messages_table = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("sender", String(255)),
    Column("text", String),
    Column("timestamp", DateTime, default=datetime.utcnow),
)

# --- ConnectionManager и FastAPI (без изменений) ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
    def disconnect(self, client_id: str):
        if client_id in self.active_connections: del self.active_connections[client_id]
    async def broadcast(self, message: str):
        for connection in self.active_connections.values(): await connection.send_text(message)
    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

manager = ConnectionManager()
app = FastAPI()
async_session = None # Инициализируем как None

# --- Функции для работы с базой (без изменений) ---
async def add_message_to_db(sender: str, text: str):
    async with async_session() as session:
        async with session.begin():
            new_message = messages_table.insert().values(sender=sender, text=text)
            await session.execute(new_message)

async def get_message_history(limit: int = 30) -> List[Dict]:
    async with async_session() as session:
        query = messages_table.select().order_by(messages_
