"""本地启动入口。依赖不全时在项目虚拟环境安装，不修改全局 Python。"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
HIDDEN = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def available(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def runtime():
    # 优先使用项目环境，也兼容本次开发已安装的上级环境。
    name = 'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
    candidates = [ROOT / '.venv' / name, ROOT.parent / '.venv' / name]
    for python in candidates:
        if python.exists() and subprocess.run([str(python), '-c', 'import fastapi,pymongo,pwdlib,jwt,uvicorn,dotenv'],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return str(python)
    target = ROOT / '.venv'
    print('首次运行：准备项目 Python 环境和依赖…', flush=True)
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(target)], check=True)
    python = target / name
    subprocess.run([sys.executable, '-m', 'pip', '--python', str(python), 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    return str(python)


def main():
    os.chdir(ROOT)
    python = runtime()
    from urllib.request import urlopen
    port = int(os.environ.get('APP_PORT', '8000'))
    if available('127.0.0.1', port):
        try:
            with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3) as response:
                data = json.load(response)
                if data.get('status') == 'ok' and data.get('database') == 'MongoDB':
                    print(f'问卷系统已经运行：http://127.0.0.1:{port}', flush=True)
                    return
        except Exception:
            pass
        raise RuntimeError(f'端口 {port} 已被其他程序占用，请设置 APP_PORT 后重试')
    # .env 的解析与后端保持一致，由已安装依赖的解释器执行。
    config = subprocess.check_output([python, '-c',
        'import json; from app.config import Settings; s=Settings(); print(json.dumps({"uri":s.mongo_uri}))'], text=True)
    uri = json.loads(config)['uri']
    if uri.rstrip('/') == 'mongodb://127.0.0.1:27018' and not available('127.0.0.1', 27018):
        executable = os.environ.get('MONGOD_PATH') or shutil.which('mongod')
        if not executable:
            fallback = Path('D:/MongoDB/Server/8.3/bin/mongod.exe')
            executable = str(fallback) if fallback.exists() else None
        if not executable:
            raise RuntimeError('未找到 mongod，请安装 MongoDB，或配置 MONGOD_PATH / MONGO_URI')
        data_dir = ROOT / '.data' / 'local-mongo'
        data_dir.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen([executable, '--dbpath', str(data_dir), '--port', '27018',
                                    '--bind_ip', '127.0.0.1', '--logpath', str(ROOT / '.data/local-mongo.log'),
                                    '--logappend', '--wiredTigerCacheSizeGB', '0.25'], **HIDDEN)
        (ROOT / '.data/mongo.pid').write_text(str(process.pid), encoding='utf-8')
        for _ in range(50):
            if available('127.0.0.1', 27018):
                break
            if process.poll() is not None:
                raise RuntimeError('MongoDB 启动失败，请查看 .data/local-mongo.log')
            time.sleep(.2)
        else:
            raise RuntimeError('MongoDB 启动超时，请查看日志')
    print(f'问卷系统：http://127.0.0.1:{port}\n接口文档：http://127.0.0.1:{port}/docs\n按 Ctrl+C 停止后端。', flush=True)
    subprocess.run([python, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)], check=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f'启动失败：{exc}', file=sys.stderr)
        sys.exit(1)
