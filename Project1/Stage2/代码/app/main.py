from contextlib import asynccontextmanager
from datetime import datetime
from bson import ObjectId
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import ENCODERS_BY_TYPE
from pymongo.errors import PyMongoError
from .config import Settings, ROOT
from .database import connect
from .errors import BusinessError
from .api import router
from .question_api import router as question_router
from .collaboration_api import router as collaboration_router

ENCODERS_BY_TYPE[ObjectId] = str


def serialize(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    return value


class MongoJSONResponse(JSONResponse):
    def render(self, content):
        return super().render(serialize(content))


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        client, db = connect(settings)
        app.state.db, app.state.settings, app.state.secret = db, settings, settings.secret()
        yield
        client.close()

    app = FastAPI(title='问卷系统 API', version='2.2.0', lifespan=lifespan,
                  default_response_class=MongoJSONResponse)

    @app.exception_handler(BusinessError)
    async def business_error(request, exc):
        return JSONResponse({'detail': exc.message, 'field': exc.field}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()]
        return JSONResponse({'detail': '输入格式不正确，请检查字段类型、长度及必填项', 'errors': errors}, status_code=422)

    @app.exception_handler(PyMongoError)
    async def database_error(request, exc):
        import logging
        logging.getLogger(__name__).exception('MongoDB operation failed', exc_info=exc)
        return JSONResponse({'detail': '数据库操作失败，请稍后重试或检查服务日志'}, status_code=503)

    app.include_router(router)
    app.include_router(question_router)
    app.include_router(collaboration_router)
    app.mount('/static', StaticFiles(directory=ROOT / 'frontend'), name='static')

    @app.get('/', include_in_schema=False)
    @app.get('/survey/{code}', include_in_schema=False)
    def index(code: str = ''):
        return FileResponse(ROOT / 'frontend' / 'index.html')

    return app


app = create_app()
