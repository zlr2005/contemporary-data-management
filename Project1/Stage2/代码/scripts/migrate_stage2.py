"""在独立第二阶段数据库迁移旧题；默认只预览，不改写数据。"""
import argparse
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pymongo import MongoClient
from app.config import Settings
from app.database import initialize
from app.errors import require
from app.questions import QuestionService, content_of, engine_questions


def migrate_database(db, apply=False):
    summary = {'apply': apply, 'legacy_surveys': 0, 'legacy_questions': 0, 'migrated_surveys': 0}
    service = QuestionService(db)
    for survey in db.surveys.find({'schema_version': 1}):
        summary['legacy_surveys'] += 1
        summary['legacy_questions'] += len(survey['questions'])
        if not apply:
            continue
        questions = []
        for q in survey['questions']:
            version = service.migrate_question(survey, q)
            require(version['content'] == content_of(q), '旧题内容与版本不一致，停止迁移以保留原始内容', 409)
            questions.append({**deepcopy(q), 'series_id': version['series_id'], 'version_id': version['_id']})
        require(engine_questions(questions) == survey['questions'], '旧题配置校验不一致，停止迁移', 409)
        result = db.surveys.update_one({'_id': survey['_id'], 'schema_version': 1,
                                       'updated_at': survey['updated_at'], 'questions': survey['questions']},
                                      {'$set': {'questions': questions, 'schema_version': 2}})
        require(result.matched_count == 1, '问卷在迁移时发生变化，请停止写入后重新执行', 409)
        summary['migrated_surveys'] += 1
    return summary


def copy_baseline(client, source_name, target, apply=False):
    require(source_name != target.name, '来源和目标数据库不能相同')
    source = client[source_name]
    require('surveys' in source.list_collection_names(), '来源没有问卷集合，请检查数据库名')
    counts = {name: source[name].count_documents({}) for name in ('users', 'surveys', 'responses')}
    if not apply:
        return counts
    require(all(target[name].count_documents({}) == 0 for name in ('users', 'surveys', 'responses',
                                                                  'question_series', 'question_versions')),
            '复制只支持空目标库；目标已有数据时请去掉 --copy-from，不能覆盖', 409)
    for name in counts:
        batch = []
        for doc in source[name].find({}):
            batch.append(doc)
            if len(batch) == 500:
                target[name].insert_many(batch)
                batch = []
        if batch:
            target[name].insert_many(batch)
        require(target[name].count_documents({}) == counts[name], '复制数量不一致，停止迁移', 409)
    return counts


def verify_baseline(source, target):
    """逐文档核对原数据及原统计；只读，不回显账号或答卷内容。"""
    from app.services import ResponseService
    checked = {}
    for name in ('users', 'surveys', 'responses'):
        count = 0
        require(source[name].count_documents({}) == target[name].count_documents({}), '迁移前后数量不一致', 409)
        for original in source[name].find({}):
            current = target[name].find_one({'_id': original['_id']})
            require(current is not None, '迁移后缺少原文档', 409)
            if name == 'surveys':
                require(ResponseService(source).statistics(original) == ResponseService(target).statistics(current),
                        '迁移前后原问卷统计不一致', 409)
                current['questions'] = engine_questions(current['questions'])
                current['schema_version'] = original['schema_version']
            require(current == original, '迁移前后原字段或答案不一致', 409)
            count += 1
        checked[name] = count
    return checked


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='确认写入独立目标库；不加则只预览')
    parser.add_argument('--database', default=Settings().database)
    parser.add_argument('--copy-from', help='先从同一 MongoDB 的旧库复制到空目标；来源只读')
    args = parser.parse_args()
    require(args.database.endswith('_stage2') or args.database.startswith('questionnaire_test_'),
            '目标需为以 _stage2 结尾的独立库或 questionnaire_test_ 测试库，禁止直接迁移第一阶段库')
    with MongoClient(Settings().mongo_uri, tz_aware=True, serverSelectionTimeoutMS=4000) as client:
        client.admin.command('ping')
        db = client[args.database]
        # 预览不运行 initialize，避免只读预览修改集合校验和索引。
        if args.apply:
            initialize(db)
        result = {'database': db.name}
        if args.copy_from:
            result['source_counts'] = copy_baseline(client, args.copy_from, db, args.apply)
        result['migration'] = migrate_database(db, args.apply)
        if args.copy_from and args.apply:
            result['verified_original_documents'] = verify_baseline(client[args.copy_from], db)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
