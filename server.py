from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json # Импортируем библиотеку для работы с JSON
from typing import Dict

# --- Создаем класс для управления соединениями ---
# Это более правильный подход, чем глобальный список.
class ConnectionManager:
    def __init__(self):
        # Словарь для хранения активных подключений: "имя_пользователя": WebSocket
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        print(f"Клиент {client_id} подключился. Всего клиентов: {len(self.active_connections)}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        print(f"Клиент {client_id} отключился. Всего клиентов: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        # Рассылаем сообщение всем подключенным клиентам
        for connection in self.active_connections.values():
            await connection.send_text(message)

# Создаем экземпляр менеджера
manager = ConnectionManager()

# Создаем экземпляр FastAPI
app = FastAPI()

# --- Обновляем наш WebSocket endpoint ---
# Теперь он принимает имя пользователя прямо в URL
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    
    # Сообщаем всем, что зашел новый пользователь
    join_message = {"sender": "Сервер", "text": f"Пользователь '{client_id}' присоединился к чату."}
    await manager.broadcast(json.dumps(join_message))

    try:
        while True:
            # Ждем сообщение от клиента
            data = await websocket.receive_text()
            
            # --- Создаем JSON-объект с данными ---
            message_data = {
                "sender": client_id, # "Подписываем" сообщение именем отправителя
                "text": data
            }
            
            # Конвертируем в строку и рассылаем всем
            await manager.broadcast(json.dumps(message_data))
            
    except WebSocketDisconnect:
        manager.disconnect(client_id)
        # Сообщаем всем, что пользователь вышел
        left_message = {"sender": "Сервер", "text": f"Пользователь '{client_id}' покинул чат."}
        await manager.broadcast(json.dumps(left_message))

