import os
from sqlalchemy import create_engine, text

print("--- НАЧИНАЮ ИМПОРТ server.py ---")

# --- 1. Настройка и проверка ---
DB_USER = os.environ.get("DB_USER")
DB_PASS = os.environ.get("DB_PASS")
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_NAME = os.environ.get("DB_NAME")

if not all([DB_USER, DB_PASS, DB_HOST, DB_PORT, DB_NAME]):
    print("--- ❌ ПРОВАЛ: Переменные для подключения к БД не установлены! ---")
    # Мы не можем остановить uvicorn, но ошибка будет в логах
else:
    print("--- ✅ Переменные окружения найдены. ---")
    try:
        # --- Собираем URL и создаем движок ---
        DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        engine = create_engine(DATABASE_URL)
        
        # --- Тестируем соединение ---
        print(f"--- Пытаюсь подключиться к {DB_HOST}... ---")
        connection = engine.connect()
        connection.execute(text("SELECT 1"))
        print("--- ✅ ТЕСТ БД УСПЕШЕН! Соединение установлено. ---")
        connection.close()

    except Exception as e:
        print("--- ❌ ТЕСТ БД ПРОВАЛЕН! Ошибка: ---")
        print(e)
        print("---------------------------------------")

# --- Оставшаяся часть кода для FastAPI ---
# Uvicorn продолжит импортировать этот код, но мы уже увидим результат теста

from fastapi import FastAPI
# ... и так далее, можно просто оставить остаток старого кода
# Он все равно упадет, но после того, как мы увидим лог теста.

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}

