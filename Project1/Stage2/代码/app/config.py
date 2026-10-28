"""环境配置集中管理，业务模块不读取环境变量。"""
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')


@dataclass
class Settings:
    mongo_uri: str = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27018')
    database: str = os.getenv('MONGO_DATABASE', 'questionnaire_stage2')
    app_port: int = int(os.getenv('APP_PORT', '8001'))
    jwt_secret: str = os.getenv('JWT_SECRET', '')
    token_hours: int = 12

    def secret(self):
        if self.jwt_secret:
            return self.jwt_secret
        # 本地开发自动创建持久密钥；多实例部署应通过环境变量配置相同密钥。
        path = ROOT / '.local-secret'
        if not path.exists():
            try:
                with path.open('x', encoding='utf-8') as f:
                    f.write(secrets.token_urlsafe(48))
            except FileExistsError:
                pass
        return path.read_text(encoding='utf-8').strip()
