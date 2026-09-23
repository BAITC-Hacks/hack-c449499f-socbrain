"""Разово создать первого пользователя. Запуск:

    python seed.py artem "Артём Е." <пароль>
"""

import sys

from app.auth import create_user
from app.db import init_db

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Использование: python seed.py <логин> <имя> <пароль>")
        sys.exit(1)

    init_db()
    login, name, password = sys.argv[1], sys.argv[2], sys.argv[3]
    user_id = create_user(login, name, password)
    print(f"Создан пользователь #{user_id}: {login} ({name})")
