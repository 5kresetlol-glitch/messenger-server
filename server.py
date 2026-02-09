import os
import json
import asyncio
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List
from datetime import datetime, timezone # <--- ИЗМЕНЕНО


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
    Column("timestamp", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)), # <--- ИЗМЕНЕНО,
)

# --- ConnectionManager и FastAPI ---
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
        # Используем asyncio.gather для параллельной рассылки
        await asyncio.gather(*(
            connection.send_text(message)
            for connection in self.active_connections.values()
        ))
    
    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

manager = ConnectionManager()
app = FastAPI()

# --- Функции для работы с базой ---
async def add_message_to_db(sender: str, text: str):
    if not async_session:
        print("ОШИБКА СОХРАНЕНИЯ: Сессия БД не создана.")
        return
    try:
        async with async_session() as session:
            await session.execute(messages_table.insert().values(sender=sender, text=text))
            await session.commit() # <--- ЯВНОЕ ПОДТВЕРЖДЕНИЕ
        print(f"Сообщение от {sender} сохранено в БД.")
    except Exception as e:
        print(f"!!! ОШИБКА при сохранении в БД: {e}")


async def get_message_history(limit: int = 30) -> List[Dict]:
    if not async_session:
        print("Ошибка: Сессия базы данных не инициализирована.")
        return []

    async with async_session() as session:
        query = messages_table.select().order_by(messages_table.c.timestamp.desc()).limit(limit)
        result = await session.execute(query)
        # Преобразуем результат в список словарей
        history = [dict(row) for row in result.mappings()]
        # Возвращаем в хронологическом порядке (от старых к новым)
        return list(reversed(history))

# --- Главный WebSocket endpoint ---
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    
    try:
        # 1. Отправляем историю только что подключившемуся клиенту
        history = await get_message_history()
        for msg in history:
            # Конвертируем datetime в строку, чтобы JSON не ругался
            msg['timestamp'] = msg['timestamp'].isoformat()
            await manager.send_personal_message(json.dumps(msg), websocket)
            
        # 2. Сообщаем всем, что зашел новый пользователь
        await manager.broadcast(json.dumps({"sender": "Сервер", "text": f"Пользователь '{client_id}' присоединился."}))

        while True:
            data = await websocket.receive_text()
            # 3. Сохраняем новое сообщение в базу
            await add_message_to_db(sender=client_id, text=data)
            
            # 4. Формируем и рассылаем сообщение всем
            message_data = { "sender": client_id, "text": data }
            await manager.broadcast(json.dumps(message_data))
            
    except WebSocketDisconnect:
        # Этот блок сработает при нормальном отключении
        manager.disconnect(client_id)
        await manager.broadcast(json.dumps({"sender": "Сервер", "text": f"Пользователь '{client_id}' покинул чат."}))
    except Exception as e:
        # Этот блок сработает при любой другой ошибке
        print(f"Произошла ошибка с клиентом {client_id}: {e}")
        manager.disconnect(client_id)
        await manager.broadcast(json.dumps({"sender": "Сервер", "text": f"Пользователь '{client_id}' отключился из-за ошибки."}))


# --- Событие при запуске сервера: создаем подключение и таблицу ---
@app.on_event("startup")
async def startup():
    global async_session
    
    # --- СОБИРАЕМ URL ВРУЧНУЮ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ---
    DB_USER = os.environ.get("DB_USER")
    DB_PASS = os.environ.get("DB_PASS")
    DB_HOST = os.environ.get("DB_HOST")
    DB_PORT = os.environ.get("DB_PORT")
    DB_NAME = os.environ.get("DB_NAME")

    if not all([DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME]):
        print("Критическая ошибка: Одна или несколько переменных для подключения к БД не установлены!")
        # Можно даже завершить работу, если база критична
        # import sys
        # sys.exit("Завершение работы из-за отсутствия настроек БД.")
        return

    # --- СОЗДАЕМ 100% ПРАВИЛЬНЫЙ URL ---
    DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    
    print("Попытка подключения к базе данных...")
    engine = create_async_engine(DATABASE_URL)

    # Создаем таблицу, если ее нет
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    
    # Создаем фабрику сессий, привязанную к движку
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    print("--- Сервер запущен, подключение к БД настроено (ручной режим). ---")
