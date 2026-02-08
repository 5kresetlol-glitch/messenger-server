import os
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List

# --- SQLAlchemy (работа с базой данных) ---
from sqlalchemy import (
    MetaData, Table, Column, Integer, String, DateTime
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Мы не создаем engine и session здесь, а только объявляем
async_session = None

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
        print(f"Клиент {client_id} подключился. Всего: {len(self.active_connections)}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        print(f"Клиент {client_id} отключился. Всего: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        for connection in self.active_connections.values():
            await connection.send_text(message)
    
    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

manager = ConnectionManager()
app = FastAPI()

# --- Новые функции для работы с базой ---
async def add_message_to_db(sender: str, text: str):
    # Проверяем, что сессия была создана
    if not async_session:
        print("Ошибка: Сессия базы данных не инициализирована.")
        return
        
    async with async_session() as session:
        async with session.begin():
            new_message = messages_table.insert().values(sender=sender, text=text)
            await session.execute(new_message)

async def get_message_history(limit: int = 30) -> List[Dict]:
    # Проверяем, что сессия была создана
    if not async_session:
        print("Ошибка: Сессия базы данных не инициализирована.")
        return []

    async with async_session() as session:
        query = messages_table.select().order_by(messages_table.c.timestamp.desc()).limit(limit)
        result = await session.execute(query)
        history = [dict(row) for row in result.mappings()]
        return list(reversed(history))

# --- Главный WebSocket endpoint ---
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    
    # 1. Отправляем историю только что подключившемуся клиенту
    history = await get_message_history()
    for msg in history:
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

# --- Событие при запуске сервера: создаем подключение и таблицу ---
@app.on_event("startup")
async def startup():
    global async_session
    
    # Получаем адрес базы из окружения
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Критическая ошибка: Переменная DATABASE_URL не установлена!")
        return

    # "Чиним" URL для SQLAlchemy, чтобы он точно использовал asyncpg
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    
    # Создаем "движок" внутри startup
    engine = create_async_engine(database_url)

    # Создаем таблицу, если ее нет
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    
    # Создаем фабрику сессий, привязанную к движку
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    print("--- Сервер запущен, подключение к базе данных настроено. ---")

