"""手动初始化与检查数据库；应用启动时也会自动执行相同初始化。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.database import connect

if __name__ == '__main__':
    client, db = connect(Settings())
    for name in ('users', 'surveys', 'responses'):
        print(name, list(db[name].index_information()))
    client.close()
