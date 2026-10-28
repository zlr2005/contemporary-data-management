"""可复用题目与不可变版本；沿用第一阶段题型校验器。"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import UUID, NAMESPACE_URL, uuid5

from bson import BSON, ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .domain import configure_questions
from .errors import BusinessError, require

CONTENT_FIELDS = ('type', 'title', 'required', 'options', 'validation')
QUESTION_FIELDS = ('id', *CONTENT_FIELDS, 'jump_rules')
REFERENCE_FIELDS = {'series_id', 'version_id'}


def clock():
    value = datetime.now(timezone.utc)
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def object_id(value):
    try:
        require(value is not None, '资源 ID 无效', 404)
        return ObjectId(value)
    except (TypeError, ValueError, InvalidId):
        raise BusinessError('资源 ID 无效', 404)


def content_of(question):
    return {key: deepcopy(question[key]) for key in CONTENT_FIELDS}


def normalize_content(content):
    require(type(content) is dict and set(content) == set(CONTENT_FIELDS), '题目内容字段不完整或含未知字段')
    configured = configure_questions([{'id': 'content', **deepcopy(content), 'jump_rules': []}])[0]
    return content_of(configured)


def engine_questions(questions):
    return [{key: deepcopy(q[key]) for key in QUESTION_FIELDS} for q in questions]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), default=str).encode('utf-8')).hexdigest()


def operation_key(*parts):
    return str(uuid5(NAMESPACE_URL, digest(parts)))


class QuestionService:
    def __init__(self, db):
        self.db = db

    def owned(self, series_id, user_id, active=False):
        series = self.db.question_series.find_one({'_id': object_id(series_id), 'owner_id': user_id})
        require(series is not None, '题目不存在或无权访问', 404)
        require(not active or series['status'] == 'active', '题目已归档，不能新增使用或版本', 409)
        return series

    def readable(self, series_id, user_id, active=False):
        series = self.db.question_series.find_one({'_id': object_id(series_id)})
        require(series is not None, '题目不存在或无权访问', 404)
        owner = series['owner_id'] == user_id
        shared = self.db.question_shares.find_one({'series_id': series['_id'], 'grantee_id': user_id, 'status': 'active'})
        require(owner or (shared and series['status'] == 'active'), '题目不存在或共享已取消', 404)
        require(not active or series['status'] == 'active', '题目已归档，不能新增使用或版本', 409)
        return series

    def version(self, version_id, user_id, active=False):
        version = self.db.question_versions.find_one({'_id': object_id(version_id)})
        require(version is not None, '题目版本不存在或无权访问', 404)
        self.readable(version['series_id'], user_id, active)
        return version

    def public_version(self, version):
        result = {key: deepcopy(value) for key, value in version.items()
                  if key not in ('request_key', 'request_hash')}
        for field in ('parent_version', 'restored_from_version'):
            source = self.db.question_versions.find_one({'_id': version[field + '_id']}) if version[field + '_id'] else None
            result[field + '_no'] = source['version_no'] if source else None
        return result

    def detail(self, series_id, user_id):
        series = self.readable(series_id, user_id)
        latest = self.db.question_versions.find_one({'series_id': series['_id']}, sort=[('version_no', -1)])
        result = {key: value for key, value in series.items()
                  if key not in ('creation_hash', 'version_counter', 'legacy_key')}
        result['latest_version'] = self.public_version(latest) if latest else None
        result['version_count'] = self.db.question_versions.count_documents({'series_id': series['_id']})
        owner = series['owner_id'] == user_id
        user = self.db.users.find_one({'_id': series['owner_id']})
        result['owner'] = {'_id': series['owner_id'], 'username': user['username'] if user else '原用户'}
        result['forked_from'] = None
        if series['forked_from_version_id']:
            source = self.db.question_versions.find_one({'_id': series['forked_from_version_id']})
            if source:
                try:
                    origin = self.readable(source['series_id'], user_id)
                    result['forked_from'] = {'series_id': origin['_id'], 'version_id': source['_id'],
                                             'name': origin['name'], 'version_no': source['version_no']}
                except BusinessError:
                    pass
        result['actions'] = {'can_edit': owner and series['status'] == 'active',
                             'can_select': series['status'] == 'active', 'can_manage': owner,
                             'can_fork': series['status'] == 'active'}
        return result

    def listing(self, user_id, page=1, size=20, status='active', keyword='', scope='owned'):
        query = {'owner_id': user_id}
        if scope == 'shared':
            ids = self.db.question_shares.distinct('series_id', {'grantee_id': user_id, 'status': 'active'})
            query = {'_id': {'$in': ids}, 'status': 'active', 'owner_id': {'$ne': user_id}}
        if status != 'all':
            query['status'] = status
        if keyword.strip():
            query['name'] = {'$regex': re.escape(keyword.strip()), '$options': 'i'}
        # 空系列可能来自中断的首次保存，不作为正式题目展示。
        series_ids = self.db.question_versions.distinct('series_id', {} if scope == 'shared' else {'created_by': user_id})
        if scope == 'shared':
            query['_id']['$in'] = list(set(query['_id']['$in']) & set(series_ids))
            query['status'] = 'active'
        else:
            query['_id'] = {'$in': series_ids}
        docs = self.db.question_series.find(query).sort([('created_at', -1), ('_id', -1)])
        return {'items': [self.detail(s['_id'], user_id) for s in docs.skip((page-1)*size).limit(size)],
                'total': self.db.question_series.count_documents(query), 'page': page, 'size': size}

    def history(self, series_id, user_id, page=1, size=20):
        series = self.readable(series_id, user_id)
        query = {'series_id': series['_id']}
        versions = self.db.question_versions.find(query).sort('version_no', -1)
        actions = {'can_edit': series['owner_id'] == user_id and series['status'] == 'active',
                   'can_select': series['status'] == 'active', 'can_manage': series['owner_id'] == user_id,
                   'can_fork': series['status'] == 'active'}
        return {'items': [{**self.public_version(v), 'source_actions': actions}
                          for v in versions.skip((page-1)*size).limit(size)],
                'total': self.db.question_versions.count_documents(query), 'page': page, 'size': size}

    def replay(self, user_id, key, fingerprint):
        try:
            require(type(key) is str, 'request_key 必须为 UUID')
            UUID(key)
        except (ValueError, AttributeError):
            raise BusinessError('request_key 必须为 UUID')
        existing = self.db.question_versions.find_one({'created_by': user_id, 'request_key': key})
        if existing:
            require(existing['request_hash'] == fingerprint, '同一请求编号不能用于不同操作或内容', 409)
        return existing

    def insert_version(self, series, user_id, content, key, fingerprint, operation,
                       parent=None, restored=None):
        existing = self.replay(user_id, key, fingerprint)
        if existing:
            return existing
        counter = self.db.question_series.find_one_and_update(
            {'_id': series['_id'], 'owner_id': user_id, 'status': 'active'},
            {'$inc': {'version_counter': 1}}, return_document=ReturnDocument.AFTER)
        require(counter is not None, '题目已归档，不能保存版本', 409)
        doc = {'_id': ObjectId(), 'series_id': series['_id'], 'version_no': counter['version_counter'],
               'content': content, 'parent_version_id': parent, 'restored_from_version_id': restored,
               'operation': operation, 'created_by': user_id, 'created_at': clock(),
               'request_key': key, 'request_hash': fingerprint, 'schema_version': 1}
        require(len(BSON.encode(doc)) < 15*1024*1024, '题目内容过大')
        try:
            self.db.question_versions.insert_one(doc)
        except DuplicateKeyError:
            existing = self.replay(user_id, key, fingerprint)
            require(existing is not None, '版本并发冲突，请重试', 409)
            return existing
        return doc

    def create(self, user_id, name, content, key, source=None, legacy_key=None):
        name = name.strip()
        require(0 < len(name) <= 200, '题目管理名称需为 1～200 字')
        content = normalize_content(content)
        fingerprint = digest(['create', name, content, source, legacy_key])
        existing = self.replay(user_id, key, fingerprint)
        if existing:
            self.owned(existing['series_id'], user_id)
            return self.detail(existing['series_id'], user_id), existing
        # 稳定系列 ID 使首次保存中断、并发重试也落在同一系列，而非创建多个空系列。
        sid = ObjectId(hashlib.sha256(f'{user_id}:{key}'.encode()).digest()[:12])
        series = {'_id': sid, 'owner_id': user_id, 'name': name, 'status': 'active',
                  'version_counter': 0, 'creation_hash': fingerprint,
                  'forked_from_series_id': source['series_id'] if source else None,
                  'forked_from_version_id': source['_id'] if source else None,
                  'created_at': clock(), 'updated_at': clock(), 'schema_version': 1}
        if legacy_key:
            series['legacy_key'] = legacy_key
        try:
            self.db.question_series.update_one({'_id': sid}, {'$setOnInsert': series}, upsert=True)
        except DuplicateKeyError:
            # 并发 upsert 的另一请求可能刚完成同一个稳定 ID。
            require(self.db.question_series.find_one({'_id': sid}) is not None, '题目创建冲突', 409)
        series = self.owned(sid, user_id, active=True)
        require(series['creation_hash'] == fingerprint, '同一请求编号不能用于不同内容', 409)
        version = self.insert_version(series, user_id, content, key, fingerprint,
                                      'fork' if source else 'migrate' if legacy_key else 'create')
        return self.detail(sid, user_id), version

    def edit(self, series_id, user_id, parent_id, content, key):
        series = self.owned(series_id, user_id, active=True)
        parent = self.version(parent_id, user_id)
        require(parent['series_id'] == series['_id'], '来源版本不属于当前题目')
        content = normalize_content(content)
        fingerprint = digest(['edit', series['_id'], parent['_id'], content])
        existing = self.replay(user_id, key, fingerprint)
        if existing:
            return existing
        require(content != parent['content'], '题目内容未变化，无需创建新版本')
        return self.insert_version(series, user_id, content, key, fingerprint, 'edit', parent['_id'])

    def restore(self, series_id, user_id, base_id, restore_id, key):
        series = self.owned(series_id, user_id, active=True)
        base, source = self.version(base_id, user_id), self.version(restore_id, user_id)
        require(base['series_id'] == source['series_id'] == series['_id'], '恢复来源必须属于当前题目')
        fingerprint = digest(['restore', series['_id'], base['_id'], source['_id']])
        return self.insert_version(series, user_id, deepcopy(source['content']), key, fingerprint,
                                   'restore', base['_id'], source['_id'])

    def patch(self, series_id, user_id, data):
        series = self.owned(series_id, user_id)
        require(bool(data), '至少提供一个修改字段')
        fields = {'updated_at': clock()}
        if 'name' in data:
            require(bool(data['name'].strip()), '题目管理名称不能为空')
            fields['name'] = data['name'].strip()
        if 'status' in data:
            fields['status'] = data['status']
        self.db.question_series.update_one({'_id': series['_id'], 'owner_id': user_id}, {'$set': fields})
        return self.detail(series['_id'], user_id)

    def usages(self, series_id, user_id, version_id=None, page=1, size=20):
        sid = object_id(series_id)
        series = self.db.question_series.find_one({'_id': sid})
        require(series is not None, '题目不存在或无权访问', 404)
        owner = series['owner_id'] == user_id
        retained = self.db.surveys.find_one({'owner_id': user_id, 'questions.series_id': sid})
        shared = self.db.question_shares.find_one({'series_id': sid, 'grantee_id': user_id, 'status': 'active'})
        require(owner or retained or (shared and series['status'] == 'active'), '题目不存在或无权访问', 404)
        match = {'series_id': series['_id']}
        if version_id:
            version = self.db.question_versions.find_one({'_id': object_id(version_id)})
            require(version is not None, '版本不存在', 404)
            require(version['series_id'] == series['_id'], '版本不属于当前题目')
            match['version_id'] = version['_id']
        query = {'questions': {'$elemMatch': match}}
        if not owner:
            query['owner_id'] = user_id
        docs = self.db.surveys.find(query).sort([('created_at', -1), ('_id', -1)])
        grants = {(g['survey_id'], g['question_id'], g['version_id']) for g in self.db.statistic_grants.find(
            {'grantee_id': user_id, 'status': 'active'})}
        items, restricted, counts = [], 0, {}
        for survey in docs:
            refs = [q for q in survey['questions'] if q.get('series_id') == sid
                    and (not version_id or q.get('version_id') == match['version_id'])]
            for vid in {q['version_id'] for q in refs}:
                counts[str(vid)] = counts.get(str(vid), 0) + 1
            visible = refs if survey['owner_id'] == user_id else [q for q in refs if
                (survey['_id'], q['id'], q['version_id']) in grants]
            if visible:
                items.append({'survey_id': survey['_id'], 'title': survey['title'], 'status': survey['status'],
                              'version_ids': [q['version_id'] for q in visible],
                              'owner_context': 'owned' if survey['owner_id'] == user_id else 'statistics_only'})
            else:
                restricted += 1
        return {'visible_items': items[(page-1)*size:page*size], 'visible_total': len(items),
                'restricted_survey_count': restricted if owner else None,
                'counts_by_version': counts, 'page': page, 'size': size}

    def migrate_question(self, survey, question):
        legacy_key = f"{survey['_id']}:{question['id']}"
        return self.create(survey['owner_id'], question['title'][:200], content_of(question),
                           operation_key('migrate', legacy_key), legacy_key=legacy_key)[1]


def bind_questions(db, questions, user_id, survey_id, previous=None):
    """先验证整卷，再建立引用；任何失败都不会部分改写原问卷。"""
    require(type(questions) is list, '题目必须为列表')
    for q in questions:
        require(type(q) is dict and set(q) <= set(QUESTION_FIELDS) | REFERENCE_FIELDS
                and set(QUESTION_FIELDS) <= set(q), '题目字段不完整或包含未知字段')
        require(('series_id' in q) == ('version_id' in q), '题目系列和版本需同时提供')
    configured = configure_questions(engine_questions(questions))
    old_questions = {q['id']: q for q in (previous or {}).get('questions', [])}
    service = QuestionService(db)
    result, seen = [], set()
    for raw, q in zip(questions, configured):
        old = old_questions.get(q['id'])
        if 'version_id' in raw:
            retained = (old and old.get('version_id') == object_id(raw['version_id'])
                        and old.get('series_id') == object_id(raw['series_id'])
                        and content_of(old) == content_of(q))
            version = (db.question_versions.find_one({'_id': old['version_id']}) if retained
                       else service.version(raw['version_id'], user_id, active=True))
            require(version is not None, '原题目版本缺失', 409)
            require(version['series_id'] == object_id(raw['series_id']), '题目系列与版本不匹配')
            require(content_of(q) == version['content'], '题目快照与正式版本不一致，请保存新版本后再使用', field=q['id'])
        elif old and old.get('version_id') and content_of(q) == content_of(old):
            version = db.question_versions.find_one({'_id': old['version_id']})
            require(version is not None, '原题目版本缺失', 409)
        else:
            base = old.get('version_id') if old else None
            key = operation_key('survey-content', user_id, survey_id, q['id'], base, content_of(q))
            if base:
                source = service.version(base, user_id, active=True)
                series = service.readable(source['series_id'], user_id, active=True)
                if series['owner_id'] == user_id:
                    version = service.edit(old['series_id'], user_id, base, content_of(q), key)
                else:
                    _, version = service.create(user_id, q['title'][:200], content_of(q), key, source=source)
            else:
                _, version = service.create(user_id, q['title'][:200], content_of(q), key)
        require(version['_id'] not in seen, '同一版本在一份问卷中只能使用一次', 409)
        seen.add(version['_id'])
        result.append({**q, 'series_id': version['series_id'], 'version_id': version['_id']})
    return result
