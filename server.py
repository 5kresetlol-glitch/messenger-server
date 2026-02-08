import os
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List

# --- SQLAlchemy (работа с базой данных) ---
from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String, DateTime
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# --- Получаем "адрес" базы данных из настроек Render ---
# Мы добавим его в переменные окружения на сайте Render
DATABASE_URL = os.environ.get("DATABASE_URL")

# Создаем "движок" для асинхронной работы с базой
engine = create_async_engine(DATABASE_URL)
# Создаем асинхронные сессии для запросов к базе
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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

# --- ConnectionManager и FastAPI (как и раньше, но с новыми функциями) ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
    async def broadcast(self, message: str):
        for connection in self.active_connections.values():
            await connection.send_text(message)
    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

manager = ConnectionManager()
app = FastAPI()

# --- Новые функции для работы с базой ---
async def add_message_to_db(sender: str, text: str):
    async with async_session() as session:
        async with session.begin():
            new_message = messages_table.insert().values(sender=sender, text=text)
            await session.execute(new_message)

async def get_message_history(limit: int = 30) -> List[Dict]:
    async with async_session() as session:
        query = messages_table.select().order_by(messages_table.c.timestamp.desc()).limit(limit)
        result = await session.execute(query)
        history = [dict(row) for row in result.mappings()]
        return list(reversed(history)) # Возвращаем в хронологическом порядке

# --- Главный WebSocket endpoint ---
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    
    # 1. Отправляем историю только что подключившемуся клиенту
    history = await get_message_history()
    for msg in history:
        # Конвертируем datetime в строку, чтобы JSON не ругался
        msg['timestamp'] = msg['timestamp'].isoformat()
        await manager.send_personal_message(json.dumps(msg), websocket)
        
    # 2. Сообщаем всем, что зашел новый пользователь
    await manager.broadcast(json.dumps({"sender": "Сервер", "text": f"Пользователь '{client_id}' присоединился."}))

    try:
        while True:
            data = await websocket.receive_text()
            # 3. Сохраняем новое сообщение в базу
            await add_message_to_db(sender=client_id, text=data)
            
            # 4. Формируем и рассылаем сообщение всем
            message_data = { "sender": client_id, "text": data }
            await manager.broadcast(json.dumps(message_data))
            
    except WebSocketDisconnect:
        manager.disconnect(client_id)
        await manager.broadcast(json.dumps({"sender": "Сервер", "text": f"Пользователь '{client_id}' покинул чат."}))

# --- Событие при запуске сервера: создаем таблицу в базе ---
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
