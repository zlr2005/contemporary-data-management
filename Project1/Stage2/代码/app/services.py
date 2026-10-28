"""应用服务：状态、权限、存储与规则引擎的协调。"""
import secrets
from datetime import datetime, timezone, timedelta
from uuid import UUID
from bson import ObjectId, BSON
from pymongo.errors import DuplicateKeyError
from .domain import configure_questions, evaluate
from .errors import BusinessError, require
from .questions import bind_questions, engine_questions, clock


def now():
    return clock()


def check_revision(doc, data):
    expected = data.get('expected_updated_at')
    if expected is not None:
        require(deadline(expected) == doc['updated_at'], '问卷已被其他页面修改，请刷新后核对', 409)


def changed_at(doc):
    return max(now(), doc['updated_at'] + timedelta(milliseconds=1))


def oid(value):
    try:
        return ObjectId(value)
    except Exception:
        raise BusinessError('无效的资源 ID', 404)


def deadline(value):
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(result.tzinfo is not None, '截止时间需要包含时区')
        return result.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        raise BusinessError('截止时间格式不正确')


def metadata(data):
    require(bool(data['title'].strip()), '问卷标题不能为空')
    return {'title': data['title'].strip(), 'description': data['description'],
            'deadline_at': deadline(data['deadline_at']), 'updated_at': now()}


def within_size(document):
    require(len(BSON.encode(document)) < 15 * 1024 * 1024, '数据过大，请减少题目、规则或答案长度')


class SurveyService:
    def __init__(self, db):
        self.db = db

    def owned(self, survey_id, user_id):
        doc = self.db.surveys.find_one({'_id': oid(survey_id), 'owner_id': user_id})
        require(doc is not None, '问卷不存在或无权访问', 404)
        return doc

    def create(self, data, user_id):
        sid = ObjectId()
        fields = metadata(data)
        questions = bind_questions(self.db, data['questions'], user_id, sid)
        doc = {**fields, '_id': sid, 'owner_id': user_id,
               'status': 'draft', 'allow_anonymous': data['allow_anonymous'],
               'allow_repeat': data['allow_repeat'], 'questions': questions,
               'published_at': None, 'closed_at': None, 'created_at': now(), 'schema_version': 2}
        for _ in range(5):
            doc['share_code'] = secrets.token_urlsafe(12)
            within_size(doc)
            try:
                self.db.surveys.insert_one(doc)
                return doc
            except DuplicateKeyError:
                continue
        raise BusinessError('生成问卷链接失败，请重试', 503)

    def save(self, survey_id, data, user_id):
        doc = self.owned(survey_id, user_id)
        require(doc['status'] == 'draft', '首次发布后不能修改题目与填写设置', 409)
        check_revision(doc, data)
        # 未迁移旧问卷保留原保存行为；显式迁移后才加入题目库引用。
        questions = (bind_questions(self.db, data['questions'], user_id, doc['_id'], doc)
                     if doc['schema_version'] == 2 else configure_questions(data['questions']))
        fields = {**metadata(data), 'questions': questions, 'updated_at': changed_at(doc),
                  'allow_anonymous': data['allow_anonymous'], 'allow_repeat': data['allow_repeat']}
        within_size({**doc, **fields})
        result = self.db.surveys.update_one({'_id': doc['_id'], 'owner_id': user_id, 'status': 'draft',
                                             'updated_at': doc['updated_at']}, {'$set': fields})
        require(result.matched_count == 1, '问卷已被其他页面修改，请刷新后重试', 409)
        return {**doc, **fields}

    def update_metadata(self, survey_id, data, user_id):
        doc = self.owned(survey_id, user_id)
        check_revision(doc, data)
        fields = {**metadata(data), 'updated_at': changed_at(doc)}
        result = self.db.surveys.update_one({'_id': doc['_id'], 'owner_id': user_id,
                                             'updated_at': doc['updated_at']}, {'$set': fields})
        require(result.matched_count == 1, '问卷已被其他页面修改，请刷新后重试', 409)
        return {**doc, **fields}

    def publish(self, survey_id, user_id):
        doc = self.owned(survey_id, user_id)
        require(doc['status'] == 'draft', '只有草稿可以发布', 409)
        configure_questions(engine_questions(doc['questions']), publishing=True)
        require(doc['deadline_at'] is None or doc['deadline_at'] > now(), '截止时间必须晚于当前时间')
        time = changed_at(doc)
        result = self.db.surveys.update_one({'_id': doc['_id'], 'status': 'draft', 'updated_at': doc['updated_at']},
                                            {'$set': {'status': 'published', 'published_at': time, 'updated_at': time}})
        require(result.matched_count == 1, '问卷已变更，请刷新后重试', 409)
        return self.owned(survey_id, user_id)

    def close(self, survey_id, user_id):
        doc = self.owned(survey_id, user_id)
        require(doc['status'] == 'published', '只有已发布问卷可以关闭', 409)
        time = now()
        result = self.db.surveys.update_one({'_id': doc['_id'], 'status': 'published'},
                                            {'$set': {'status': 'closed', 'closed_at': time, 'updated_at': time}})
        require(result.matched_count == 1, '问卷状态已改变，请刷新', 409)
        return self.owned(survey_id, user_id)

    def available(self, code):
        doc = self.db.surveys.find_one({'share_code': code})
        require(doc is not None, '问卷不存在', 404)
        require(doc['status'] == 'published', '问卷尚未发布或已经关闭', 409)
        require(doc['deadline_at'] is None or now() < doc['deadline_at'], '问卷已超过截止时间', 409)
        return doc


class ResponseService:
    def __init__(self, db):
        self.db, self.surveys = db, SurveyService(db)

    def submit(self, code, user_id, data):
        try:
            UUID(data['submission_key'])
        except ValueError:
            raise BusinessError('submission_key 必须为 UUID')
        survey = self.db.surveys.find_one({'share_code': code})
        require(survey is not None, '问卷不存在', 404)
        key = {'survey_id': survey['_id'], 'respondent_id': user_id, 'submission_key': data['submission_key']}
        existing = self.db.responses.find_one(key)
        if existing:
            result = evaluate(survey['questions'], data['answers'])
            require(existing['answers'] == result['answers'], '同一提交编号不能用于不同答案', 409)
            return existing
        survey = self.surveys.available(code)
        received_at = now()
        result = evaluate(survey['questions'], data['answers'])
        doc = {'_id': ObjectId(), **key, 'repeat_allowed': survey['allow_repeat'],
               'path': result['path'], 'answers': result['answers'],
               'submitted_at': received_at, 'schema_version': 1}
        within_size(doc)
        try:
            self.db.responses.insert_one(doc)
        except DuplicateKeyError:
            existing = self.db.responses.find_one(key)
            if existing:
                require(existing['answers'] == doc['answers'], '同一提交编号不能用于不同答案', 409)
                return existing
            raise BusinessError('该问卷不允许重复填写，你已经提交过', 409)
        return doc

    def statistics(self, survey, question_id=None):
        questions = [q for q in survey['questions'] if question_id is None or q['id'] == question_id]
        require(bool(questions) or question_id is None, '题目不存在', 404)
        sid = survey['_id']
        stats = []
        for q in questions:
            base = [{'$match': {'survey_id': sid}}, {'$unwind': '$answers'},
                    {'$match': {'answers.question_id': q['id']}}]
            count = list(self.db.responses.aggregate(base + [{'$count': 'n'}]))
            item = {'question_id': q['id'], 'title': q['title'], 'type': q['type'],
                    'answered': count[0]['n'] if count else 0}
            if q['type'] in ('single', 'multiple'):
                pipeline = base + ([{'$unwind': '$answers.value'}] if q['type'] == 'multiple' else [])
                counts = {row['_id']: row['count'] for row in self.db.responses.aggregate(
                    pipeline + [{'$group': {'_id': '$answers.value', 'count': {'$sum': 1}}}])}
                item['options'] = [{**o, 'count': counts.get(o['id'], 0)} for o in q['options']]
            elif q['type'] == 'number':
                avg = list(self.db.responses.aggregate(base + [{'$group': {'_id': None, 'average': {'$avg': '$answers.value'}}}]))
                item['average'] = avg[0]['average'] if avg else None
            stats.append(item)
        return {'total_responses': self.db.responses.count_documents({'survey_id': sid}), 'questions': stats}

    def contents(self, survey, question_id, page, size):
        q = next((q for q in survey['questions'] if q['id'] == question_id), None)
        require(q is not None, '题目不存在', 404)
        require(q['type'] in ('text', 'number'), '该接口用于填空内容')
        rows = self.db.responses.aggregate([
            {'$match': {'survey_id': survey['_id']}}, {'$sort': {'submitted_at': -1}},
            {'$unwind': '$answers'}, {'$match': {'answers.question_id': question_id}},
            {'$skip': (page - 1) * size}, {'$limit': size},
            {'$project': {'_id': 0, 'value': '$answers.value'}}])
        return {'page': page, 'items': list(rows)}
