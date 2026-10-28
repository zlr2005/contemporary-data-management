from typing import Literal
from fastapi import APIRouter, Depends, Query

from .api import database, user
from .models import ShareInput, StatisticGrantInput, BankCreate, BankSave, BankDelete
from .collaboration_services import ShareService, BankService, StatisticGrantService
from .cross_statistics import CrossStatistics

router = APIRouter(prefix='/api')


@router.get('/question-series/{series_id}/shares')
def shares(series_id: str, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
           current=Depends(user), db=Depends(database)):
    return ShareService(db).listing(series_id, current['_id'], page, size)


@router.put('/question-series/{series_id}/shares')
def share(series_id: str, data: ShareInput, current=Depends(user), db=Depends(database)):
    return ShareService(db).grant(series_id, current['_id'], data.username)


@router.delete('/question-series/{series_id}/shares/{grantee_id}')
def revoke_share(series_id: str, grantee_id: str, current=Depends(user), db=Depends(database)):
    return ShareService(db).revoke(series_id, current['_id'], grantee_id)


@router.get('/question-banks')
def banks(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), current=Depends(user), db=Depends(database)):
    return BankService(db).listing(current['_id'], page, size)


@router.post('/question-banks', status_code=201)
def create_bank(data: BankCreate, current=Depends(user), db=Depends(database)):
    return BankService(db).create(current['_id'], data.name, data.description)


@router.get('/question-banks/{bank_id}')
def bank_detail(bank_id: str, current=Depends(user), db=Depends(database)):
    return BankService(db).detail(bank_id, current['_id'])


@router.put('/question-banks/{bank_id}')
def save_bank(bank_id: str, data: BankSave, current=Depends(user), db=Depends(database)):
    return BankService(db).save(bank_id, current['_id'], data.model_dump())


@router.delete('/question-banks/{bank_id}')
def delete_bank(bank_id: str, data: BankDelete, current=Depends(user), db=Depends(database)):
    return BankService(db).delete(bank_id, current['_id'], data.revision)


@router.get('/surveys/{sid}/questions/{qid}/statistic-grants')
def grants(sid: str, qid: str, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
           current=Depends(user), db=Depends(database)):
    return StatisticGrantService(db).listing(sid, qid, current['_id'], page, size)


@router.put('/surveys/{sid}/questions/{qid}/statistic-grants')
def grant(sid: str, qid: str, data: StatisticGrantInput, current=Depends(user), db=Depends(database)):
    return StatisticGrantService(db).grant(sid, qid, current['_id'], data.username, data.allow_contents)


@router.delete('/surveys/{sid}/questions/{qid}/statistic-grants/{grantee_id}')
def revoke_grant(sid: str, qid: str, grantee_id: str, current=Depends(user), db=Depends(database)):
    return StatisticGrantService(db).revoke(sid, qid, current['_id'], grantee_id)


@router.get('/question-statistics/versions')
def statistic_versions(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                       keyword: str = Query('', max_length=200), series_id: str | None = None,
                       current=Depends(user), db=Depends(database)):
    return CrossStatistics(db).listing(current['_id'], page, size, keyword, series_id)


@router.get('/question-statistics/versions/{version_id}')
def cross_statistics(version_id: str, scope: Literal['all', 'own', 'authorized'] = 'all',
                     boundaries: list[float] | None = Query(None), current=Depends(user), db=Depends(database)):
    return CrossStatistics(db).statistics(version_id, current['_id'], scope, boundaries)


@router.get('/question-statistics/versions/{version_id}/sources')
def statistic_sources(version_id: str, scope: Literal['all', 'own', 'authorized'] = 'all',
                      page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                      current=Depends(user), db=Depends(database)):
    return CrossStatistics(db).source_page(version_id, current['_id'], scope, page, size)


@router.get('/question-statistics/versions/{version_id}/contents')
def statistic_contents(version_id: str, scope: Literal['all', 'own', 'authorized'] = 'all',
                       page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                       current=Depends(user), db=Depends(database)):
    return CrossStatistics(db).contents(version_id, current['_id'], scope, page, size)
