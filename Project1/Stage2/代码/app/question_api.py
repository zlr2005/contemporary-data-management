"""第一批第二阶段接口：自有题目、版本与使用情况。"""
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from .api import database, user
from .errors import require
from .models import QuestionCreate, VersionCreate, VersionRestore, QuestionPatch
from .questions import QuestionService

router = APIRouter(prefix='/api')


def creation_status(db, uid, key, response):
    response.status_code = 200 if db.question_versions.find_one({'created_by': uid, 'request_key': key}) else 201


@router.get('/question-series')
def listing(scope: Literal['owned', 'shared'] = 'owned', status: Literal['active', 'archived', 'all'] = 'active',
            keyword: str = Query('', max_length=200), page: int = Query(1, ge=1),
            size: int = Query(20, ge=1, le=100), current=Depends(user), db=Depends(database)):
    return QuestionService(db).listing(current['_id'], page, size, status, keyword, scope)


@router.post('/question-series')
def create(data: QuestionCreate, response: Response, current=Depends(user), db=Depends(database)):
    creation_status(db, current['_id'], data.request_key, response)
    service = QuestionService(db)
    series, version = service.create(current['_id'], data.name, data.content, data.request_key)
    return {'series': series, 'version': service.public_version(version)}


@router.get('/question-series/{series_id}')
def detail(series_id: str, current=Depends(user), db=Depends(database)):
    return QuestionService(db).detail(series_id, current['_id'])


@router.patch('/question-series/{series_id}')
def patch(series_id: str, data: QuestionPatch, current=Depends(user), db=Depends(database)):
    require(all(value is not None for value in data.model_dump(exclude_unset=True).values()), '修改字段不能为 null')
    return QuestionService(db).patch(series_id, current['_id'], data.model_dump(exclude_unset=True))


@router.get('/question-series/{series_id}/versions')
def history(series_id: str, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
            current=Depends(user), db=Depends(database)):
    return QuestionService(db).history(series_id, current['_id'], page, size)


@router.get('/question-versions/{version_id}')
def version_detail(version_id: str, current=Depends(user), db=Depends(database)):
    service = QuestionService(db)
    return service.public_version(service.version(version_id, current['_id']))


@router.post('/question-series/{series_id}/versions')
def edit(series_id: str, data: VersionCreate, response: Response, current=Depends(user), db=Depends(database)):
    creation_status(db, current['_id'], data.request_key, response)
    service = QuestionService(db)
    return service.public_version(service.edit(series_id, current['_id'], data.parent_version_id,
                                               data.content, data.request_key))


@router.post('/question-series/{series_id}/restorations')
def restore(series_id: str, data: VersionRestore, response: Response, current=Depends(user), db=Depends(database)):
    creation_status(db, current['_id'], data.request_key, response)
    service = QuestionService(db)
    return service.public_version(service.restore(series_id, current['_id'], data.base_version_id,
                                                  data.restore_version_id, data.request_key))


@router.post('/question-versions/{version_id}/forks')
def fork(version_id: str, data: QuestionCreate, response: Response, current=Depends(user), db=Depends(database)):
    service = QuestionService(db)
    source = service.version(version_id, current['_id'], active=True)
    creation_status(db, current['_id'], data.request_key, response)
    series, version = service.create(current['_id'], data.name, data.content, data.request_key, source=source)
    return {'series': series, 'version': service.public_version(version)}


@router.get('/question-series/{series_id}/usages')
def usages(series_id: str, version_id: str | None = None, page: int = Query(1, ge=1),
           size: int = Query(20, ge=1, le=100), current=Depends(user), db=Depends(database)):
    return QuestionService(db).usages(series_id, current['_id'], version_id, page, size)
