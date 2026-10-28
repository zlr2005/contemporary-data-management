"""按当前权限、具体版本和问卷题目配对统计，不合并不同版本。"""
import re
from copy import deepcopy

from .domain import finite_number
from .errors import BusinessError, require
from .questions import QuestionService, object_id


class CrossStatistics:
    def __init__(self, db):
        self.db, self.questions = db, QuestionService(db)

    @staticmethod
    def version_info(version):
        return {k: deepcopy(version[k]) for k in ('_id', 'series_id', 'version_no', 'content')}

    def sources(self, version_id, uid, scope='all'):
        vid = object_id(version_id)
        version = self.db.question_versions.find_one({'_id': vid})
        require(version is not None, '题目版本不存在或无权访问', 404)
        sources = {}
        for survey in self.db.surveys.find({'owner_id': uid, 'questions.version_id': vid}):
            for q in survey['questions']:
                if q.get('version_id') == vid:
                    sources[(survey['_id'], q['id'])] = self.source_info(survey, q, True, True)
        for grant in self.db.statistic_grants.find({'grantee_id': uid, 'status': 'active', 'version_id': vid}):
            survey = self.db.surveys.find_one({'_id': grant['survey_id'], 'published_at': {'$ne': None}})
            if not survey or survey['owner_id'] == uid:
                continue
            question = next((q for q in survey['questions'] if q['id'] == grant['question_id'] and q.get('version_id') == vid), None)
            if question:
                sources[(survey['_id'], question['id'])] = self.source_info(survey, question, False, grant['allow_contents'])
        readable = False
        try:
            self.questions.version(vid, uid)
            readable = True
        except BusinessError:
            pass
        require(readable or bool(sources), '题目版本不存在或统计权限已取消', 404)
        selected = [s for s in sources.values() if scope == 'all' or s['owned'] == (scope == 'own')]
        selected.sort(key=lambda s: (str(s['survey_id']), s['question_id']))
        return version, selected

    @staticmethod
    def source_info(survey, question, owned, contents):
        return {'survey_id': survey['_id'], 'question_id': question['id'], 'version_id': question['version_id'],
                'title': survey['title'], 'status': survey['status'], 'owned': owned, 'allow_contents': contents}

    def listing(self, uid, page, size, keyword='', series_id=None):
        series_ids = self.db.question_series.distinct('_id', {'owner_id': uid})
        shared = self.db.question_shares.distinct('series_id', {'grantee_id': uid, 'status': 'active'})
        series_ids += self.db.question_series.distinct('_id', {'_id': {'$in': shared}, 'status': 'active'})
        ids = set(self.db.question_versions.distinct('_id', {'series_id': {'$in': series_ids}}))
        for survey in self.db.surveys.find({'owner_id': uid}, {'questions': 1}):
            ids.update(q['version_id'] for q in survey['questions'] if 'version_id' in q)
        for grant in self.db.statistic_grants.find({'grantee_id': uid, 'status': 'active'}):
            survey = self.db.surveys.find_one({'_id': grant['survey_id'], 'published_at': {'$ne': None},
                                              'questions': {'$elemMatch': {'id': grant['question_id'], 'version_id': grant['version_id']}}})
            if survey:
                ids.add(grant['version_id'])
        query = {'_id': {'$in': list(ids)}}
        if keyword.strip():
            query['content.title'] = {'$regex': re.escape(keyword.strip()), '$options': 'i'}
        if series_id:
            query['series_id'] = object_id(series_id)
        docs = self.db.question_versions.find(query).sort([('created_at', -1), ('_id', -1)])
        return {'items': [self.version_info(v) for v in docs.skip((page-1)*size).limit(size)],
                'total': self.db.question_versions.count_documents(query), 'page': page, 'size': size}

    @staticmethod
    def pipeline(sources):
        if not sources:
            return [{'$match': {'_id': {'$exists': False}}}]
        return [{'$match': {'survey_id': {'$in': list({s['survey_id'] for s in sources})}}},
                {'$unwind': '$answers'}, {'$match': {'$or': [
                    {'survey_id': s['survey_id'], 'answers.question_id': s['question_id']} for s in sources]}}]

    def count(self, sources):
        rows = list(self.db.responses.aggregate(self.pipeline(sources) + [{'$count': 'n'}]))
        return rows[0]['n'] if rows else 0

    def statistics(self, vid, uid, scope='all', boundaries=None):
        version, sources = self.sources(vid, uid, scope)
        kind = version['content']['type']
        if boundaries is not None:
            require(kind == 'number', '只有数字题支持分布边界')
            require(2 <= len(boundaries) <= 20 and all(finite_number(x) for x in boundaries)
                    and all(a < b for a, b in zip(boundaries, boundaries[1:])), '分布边界必须是 2～20 个严格递增的有限数字')
        base = self.pipeline(sources)
        answered = self.count(sources)
        supports_contents = kind in ('text', 'number')
        content_sources = [s for s in sources if s['allow_contents']] if supports_contents else []
        content_count = self.count(content_sources)
        result = {'version': self.version_info(version), 'scope': scope,
                  'source_question_count': len(sources), 'source_survey_count': len({s['survey_id'] for s in sources}),
                  'total_responses': self.db.responses.count_documents({'survey_id': {'$in': list({s['survey_id'] for s in sources})}}),
                  'answered': answered, 'content_access': {'source_question_count': len(content_sources),
                    'answered': content_count, 'supported': supports_contents,
                    'partial': supports_contents and (content_count != answered or len(content_sources) != len(sources))}}
        if kind in ('single', 'multiple'):
            stages = base + ([{'$unwind': '$answers.value'}] if kind == 'multiple' else [])
            counts = {row['_id']: row['n'] for row in self.db.responses.aggregate(stages + [
                {'$group': {'_id': '$answers.value', 'n': {'$sum': 1}}}])}
            result['options'] = [{**o, 'count': counts.get(o['id'], 0)} for o in version['content']['options']]
        elif kind == 'number':
            rows = list(self.db.responses.aggregate(base + [{'$group': {'_id': None,
                'average': {'$avg': '$answers.value'}, 'minimum': {'$min': '$answers.value'}, 'maximum': {'$max': '$answers.value'}}}]))
            result.update({k: rows[0][k] if rows else None for k in ('average', 'minimum', 'maximum')})
            result['distribution'] = self.distribution(base, result['minimum'], result['maximum'], boundaries)
        return result

    def distribution(self, base, minimum, maximum, boundaries):
        if minimum is None:
            return []
        if boundaries is not None:
            bins = [{'min': None if i == 0 else boundaries[i-1], 'max': boundaries[i] if i < len(boundaries) else None,
                     'include_min': i > 0, 'include_max': False} for i in range(len(boundaries)+1)]
            expression = {'$switch': {'branches': [{'case': {'$lt': ['$answers.value', value]}, 'then': i}
                                                  for i, value in enumerate(boundaries)], 'default': len(boundaries)}}
        elif minimum == maximum:
            bins = [{'min': minimum, 'max': maximum, 'include_min': True, 'include_max': True}]
            expression = {'$literal': 0}
        else:
            # 极小数或相邻浮点值可能产生重合边界；合并后仍确保每个值只计一次。
            edges = sorted(set([minimum, maximum] + [minimum+(maximum-minimum)*(i/10) for i in range(1, 10)]))
            bins = [{'min': a, 'max': b, 'include_min': True, 'include_max': i == len(edges)-2}
                    for i, (a, b) in enumerate(zip(edges, edges[1:]))]
            expression = ({'$switch': {'branches': [{'case': {'$lt': ['$answers.value', boundary]}, 'then': i}
                         for i, boundary in enumerate(edges[1:-1])], 'default': len(bins)-1}}
                          if len(bins) > 1 else {'$literal': 0})
        counts = {int(row['_id']): row['n'] for row in self.db.responses.aggregate(base + [
            {'$group': {'_id': expression, 'n': {'$sum': 1}}}])}
        return [{**bucket, 'count': counts.get(i, 0)} for i, bucket in enumerate(bins)]

    def source_page(self, vid, uid, scope, page, size):
        _, sources = self.sources(vid, uid, scope)
        return {'items': sources[(page-1)*size:page*size], 'total': len(sources), 'page': page, 'size': size, 'scope': scope}

    def contents(self, vid, uid, scope, page, size):
        version, sources = self.sources(vid, uid, scope)
        require(version['content']['type'] in ('text', 'number'), '只有填空题支持填写内容查询')
        permitted = [s for s in sources if s['allow_contents']]
        rows = list(self.db.responses.aggregate(self.pipeline(permitted) + [
            {'$sort': {'submitted_at': -1, '_id': -1}}, {'$skip': (page-1)*size}, {'$limit': size},
            {'$project': {'_id': 0, 'value': '$answers.value'}}]))
        return {'items': rows, 'total': self.count(permitted), 'page': page, 'size': size, 'scope': scope,
                'content_source_question_count': len(permitted)}
