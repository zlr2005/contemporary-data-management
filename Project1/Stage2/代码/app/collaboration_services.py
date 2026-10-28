"""题目使用授权、题库与单题统计授权。权限与题目版本分别管理。"""
from copy import deepcopy
from bson import BSON, ObjectId
from pymongo.errors import DuplicateKeyError

from .errors import BusinessError, require
from .questions import QuestionService, clock, object_id


def recipient(db, username, user_id):
    person = db.users.find_one({'username_key': username.strip().casefold()})
    require(person is not None, '用户尚未注册，请检查用户名')
    require(person['_id'] != user_id, '无需向自己授权')
    return person


def upsert_grant(collection, key, fields):
    timestamp = clock()
    change = {'$set': {**fields, 'status': 'active', 'updated_at': timestamp, 'revoked_at': None},
              '$setOnInsert': {**key, 'created_at': timestamp, 'schema_version': 1}}
    try:
        collection.update_one(key, change, upsert=True)
    except DuplicateKeyError:
        collection.update_one(key, {'$set': change['$set']})
    return collection.find_one(key)


def grant_list(db, collection, query, page, size):
    items = list(collection.find(query).sort([('created_at', -1), ('_id', -1)]).skip((page-1)*size).limit(size))
    for item in items:
        person = db.users.find_one({'_id': item['grantee_id']})
        item['username'] = person['username'] if person else '原用户'
    return {'items': items, 'total': collection.count_documents(query), 'page': page, 'size': size}


class ShareService:
    def __init__(self, db):
        self.db = db

    def listing(self, sid, uid, page, size):
        series = QuestionService(self.db).owned(sid, uid)
        return grant_list(self.db, self.db.question_shares, {'series_id': series['_id']}, page, size)

    def grant(self, sid, uid, username):
        series = QuestionService(self.db).owned(sid, uid, active=True)
        person = recipient(self.db, username, uid)
        return upsert_grant(self.db.question_shares, {'series_id': series['_id'], 'grantee_id': person['_id']},
                            {'granted_by': uid})

    def revoke(self, sid, uid, grantee):
        series = QuestionService(self.db).owned(sid, uid)
        self.db.question_shares.update_one({'series_id': series['_id'], 'grantee_id': object_id(grantee)},
            {'$set': {'status': 'revoked', 'updated_at': clock(), 'revoked_at': clock()}})
        return {'status': 'revoked'}


class BankService:
    def __init__(self, db):
        self.db, self.questions = db, QuestionService(db)

    def owned(self, bid, uid):
        doc = self.db.question_banks.find_one({'_id': object_id(bid), 'owner_id': uid})
        require(doc is not None, '题库不存在或无权访问', 404)
        return doc

    def listing(self, uid, page, size):
        query = {'owner_id': uid}
        items = []
        for bank in self.db.question_banks.find(query).sort([('updated_at', -1), ('_id', -1)]).skip((page-1)*size).limit(size):
            bank['member_count'] = len(bank.pop('items'))
            items.append(bank)
        return {'items': items, 'total': self.db.question_banks.count_documents(query), 'page': page, 'size': size}

    def create(self, uid, name, description):
        require(bool(name.strip()), '题库名称不能为空')
        doc = {'_id': ObjectId(), 'owner_id': uid, 'name': name.strip(), 'description': description,
               'items': [], 'revision': 1, 'created_at': clock(), 'updated_at': clock(), 'schema_version': 1}
        self.db.question_banks.insert_one(doc)
        return self.detail(doc['_id'], uid)

    def detail(self, bid, uid):
        doc = self.owned(bid, uid)
        for item in doc['items']:
            version = self.db.question_versions.find_one({'_id': item['version_id']})
            item['version_no'] = version['version_no'] if version else None
            item['actions'] = {'can_select': False, 'can_update': False, 'can_view_history': False}
            item['source_actions'] = {'can_edit': False, 'can_fork': False, 'can_manage': False, 'can_select': False}
            item['unavailable_reason'] = '共享已取消或题目已归档，仅保留已有条目'
            item['latest_version_no'] = None
            try:
                series = self.questions.readable(item['series_id'], uid)
                active = series['status'] == 'active'
                latest = self.db.question_versions.find_one({'series_id': series['_id']}, sort=[('version_no', -1)])
                item['latest_version_no'] = latest['version_no'] if latest else None
                item['actions'] = {'can_select': active, 'can_update': active and latest is not None
                                   and latest['_id'] != item['version_id'], 'can_view_history': True}
                item['source_actions'] = {'can_edit': active and series['owner_id'] == uid,
                                          'can_fork': active, 'can_manage': series['owner_id'] == uid,
                                          'can_select': active}
                item['unavailable_reason'] = '' if active else '题目已归档，仅保留已有条目'
            except BusinessError:
                pass
        return doc

    def save(self, bid, uid, data):
        doc = self.owned(bid, uid)
        require(doc['revision'] == data['revision'], '题库已被其他页面修改，请刷新核对', 409)
        require(bool(data['name'].strip()), '题库名称不能为空')
        ids = [object_id(v) for v in data['version_ids']]
        require(len(ids) == len(set(ids)), '同一版本在同一题库中只能出现一次', 409)
        previous = {i['version_id']: i for i in doc['items']}
        items = []
        for vid in ids:
            if vid in previous:
                items.append(deepcopy(previous[vid]))
            else:
                version = self.questions.version(vid, uid, active=True)
                items.append({'series_id': version['series_id'], 'version_id': vid,
                              'content': deepcopy(version['content']), 'added_at': clock()})
        fields = {'name': data['name'].strip(), 'description': data['description'], 'items': items,
                  'updated_at': clock(), 'revision': doc['revision'] + 1}
        require(len(BSON.encode({**doc, **fields})) < 15*1024*1024, '题库内容过大，请减少成员')
        result = self.db.question_banks.update_one({'_id': doc['_id'], 'owner_id': uid,
                                                   'revision': data['revision']}, {'$set': fields})
        require(result.matched_count == 1, '题库已被其他页面修改，请刷新核对', 409)
        return self.detail(doc['_id'], uid)

    def delete(self, bid, uid, revision):
        doc = self.owned(bid, uid)
        result = self.db.question_banks.delete_one({'_id': doc['_id'], 'owner_id': uid, 'revision': revision})
        require(result.deleted_count == 1, '题库已被其他页面修改，请刷新核对', 409)
        return {'deleted': True}


class StatisticGrantService:
    def __init__(self, db):
        self.db = db

    def owned_question(self, sid, qid, uid):
        survey = self.db.surveys.find_one({'_id': object_id(sid), 'owner_id': uid})
        require(survey is not None, '问卷不存在或无权访问', 404)
        question = next((q for q in survey['questions'] if q['id'] == qid), None)
        require(question is not None, '题目不存在', 404)
        require(survey['published_at'] is not None, '问卷首次发布后才能授权统计', 409)
        require('version_id' in question, '请先完成旧数据迁移', 409)
        return survey, question

    def listing(self, sid, qid, uid, page, size):
        survey, _ = self.owned_question(sid, qid, uid)
        return grant_list(self.db, self.db.statistic_grants, {'survey_id': survey['_id'], 'question_id': qid}, page, size)

    def grant(self, sid, qid, uid, username, allow_contents=False):
        survey, question = self.owned_question(sid, qid, uid)
        require(not allow_contents or question['type'] in ('text', 'number'), '只有填空题可授权查看填写内容')
        person = recipient(self.db, username, uid)
        return upsert_grant(self.db.statistic_grants,
            {'survey_id': survey['_id'], 'question_id': qid, 'grantee_id': person['_id']},
            {'version_id': question['version_id'], 'granted_by': uid, 'allow_contents': allow_contents})

    def revoke(self, sid, qid, uid, grantee):
        survey, _ = self.owned_question(sid, qid, uid)
        self.db.statistic_grants.update_one({'survey_id': survey['_id'], 'question_id': qid,
                                            'grantee_id': object_id(grantee)},
            {'$set': {'status': 'revoked', 'updated_at': clock(), 'revoked_at': clock()}})
        return {'status': 'revoked'}
