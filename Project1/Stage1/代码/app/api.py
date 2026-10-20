from fastapi import APIRouter, Depends, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pymongo.errors import DuplicateKeyError
from .errors import require, BusinessError
from .models import Credentials, SurveyInput, MetadataInput, AnswerRequest, SubmitRequest
from .security import hasher, DUMMY_HASH, issue_token, read_token
from .services import SurveyService, ResponseService, now
from .domain import evaluate, HANDLERS

router = APIRouter(prefix='/api')
bearer = HTTPBearer(auto_error=False)


def database(request: Request):
    return request.app.state.db


def user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    require(credentials is not None and credentials.scheme.lower() == 'bearer', '请先登录', 401)
    uid = read_token(credentials.credentials, request.app.state.secret)
    doc = request.app.state.db.users.find_one({'_id': uid})
    require(doc is not None, '账号不存在，请重新登录', 401)
    return doc


def public_user(doc):
    return {'id': str(doc['_id']), 'username': doc['username'], 'created_at': doc['created_at']}


@router.get('/health')
def health(db=Depends(database)):
    db.command('ping')
    return {'status': 'ok', 'database': 'MongoDB'}


@router.post('/auth/register', status_code=201)
def register(data: Credentials, db=Depends(database)):
    name = data.username.strip()
    require(bool(name), '用户名不能为空')
    doc = {'username': name, 'username_key': name.casefold(), 'password_hash': hasher.hash(data.password),
           'created_at': now(), 'schema_version': 1}
    try:
        db.users.insert_one(doc)
    except DuplicateKeyError:
        raise BusinessError('用户名已被注册', 409)
    return public_user(doc)


@router.post('/auth/login')
def login(data: Credentials, request: Request, db=Depends(database)):
    doc = db.users.find_one({'username_key': data.username.strip().casefold()})
    valid = hasher.verify(data.password, doc['password_hash'] if doc else DUMMY_HASH)
    require(doc is not None and valid, '用户名或密码错误', 401)
    return {'access_token': issue_token(doc['_id'], request.app.state.secret, request.app.state.settings.token_hours),
            'token_type': 'bearer', 'user': public_user(doc)}


@router.get('/auth/me')
def me(current=Depends(user)):
    return public_user(current)


@router.get('/capabilities')
def capabilities(current=Depends(user)):
    return {'question_types': list(HANDLERS),
            'operators': {name: sorted(handler.operators) for name, handler in HANDLERS.items()},
            'limits': {'questions': 100, 'options': 50, 'rules': 20, 'text_length': 10000}}


@router.get('/surveys')
def surveys(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
            current=Depends(user), db=Depends(database)):
    query = {'owner_id': current['_id']}
    docs = list(db.surveys.find(query, {'questions': 0}).sort('created_at', -1).skip((page-1)*size).limit(size))
    return {'items': docs, 'total': db.surveys.count_documents(query), 'page': page}


@router.post('/surveys', status_code=201)
def create(data: SurveyInput, current=Depends(user), db=Depends(database)):
    return SurveyService(db).create(data.model_dump(), current['_id'])


@router.get('/surveys/{sid}')
def detail(sid: str, current=Depends(user), db=Depends(database)):
    return SurveyService(db).owned(sid, current['_id'])


@router.put('/surveys/{sid}')
def save(sid: str, data: SurveyInput, current=Depends(user), db=Depends(database)):
    return SurveyService(db).save(sid, data.model_dump(), current['_id'])


@router.patch('/surveys/{sid}')
def patch(sid: str, data: MetadataInput, current=Depends(user), db=Depends(database)):
    return SurveyService(db).update_metadata(sid, data.model_dump(), current['_id'])


@router.post('/surveys/{sid}/publish')
def publish(sid: str, current=Depends(user), db=Depends(database)):
    return SurveyService(db).publish(sid, current['_id'])


@router.post('/surveys/{sid}/close')
def close(sid: str, current=Depends(user), db=Depends(database)):
    return SurveyService(db).close(sid, current['_id'])


@router.post('/surveys/{sid}/preview')
def preview(sid: str, data: AnswerRequest, current=Depends(user), db=Depends(database)):
    doc = SurveyService(db).owned(sid, current['_id'])
    return evaluate(doc['questions'], data.model_dump()['answers'], partial=True)


@router.get('/surveys/{sid}/statistics')
def statistics(sid: str, question_id: str | None = None, current=Depends(user), db=Depends(database)):
    doc = SurveyService(db).owned(sid, current['_id'])
    return ResponseService(db).statistics(doc, question_id)


@router.get('/surveys/{sid}/questions/{qid}/contents')
def contents(sid: str, qid: str, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
             current=Depends(user), db=Depends(database)):
    doc = SurveyService(db).owned(sid, current['_id'])
    return ResponseService(db).contents(doc, qid, page, size)


@router.get('/surveys/{sid}/responses')
def responses(sid: str, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
              current=Depends(user), db=Depends(database)):
    survey = SurveyService(db).owned(sid, current['_id'])
    projection = {'_id': 1, 'path': 1, 'answers': 1, 'submitted_at': 1}
    if not survey['allow_anonymous']:
        projection['respondent_id'] = 1
    rows = list(db.responses.find({'survey_id': survey['_id']}, projection)
                .sort('submitted_at', -1).skip((page-1)*size).limit(size))
    return {'items': rows, 'page': page}


@router.get('/fill/{code}')
def fill(code: str, current=Depends(user), db=Depends(database)):
    doc = SurveyService(db).available(code)
    return {key: doc[key] for key in ('title', 'description', 'share_code', 'allow_anonymous',
                                      'allow_repeat', 'deadline_at', 'questions')}


@router.post('/fill/{code}/evaluate')
def navigation(code: str, data: AnswerRequest, current=Depends(user), db=Depends(database)):
    doc = SurveyService(db).available(code)
    return evaluate(doc['questions'], data.model_dump()['answers'], partial=True)


@router.post('/fill/{code}/submit')
def submit(code: str, data: SubmitRequest, current=Depends(user), db=Depends(database)):
    doc = ResponseService(db).submit(code, current['_id'], data.model_dump())
    return {'response_id': str(doc['_id']), 'submitted_at': doc['submitted_at']}
