from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

from bson import ObjectId
from pymongo.errors import WriteError
import pytest

from conftest import question, payload, publish
from app.questions import content_of, engine_questions
from app.errors import BusinessError
from scripts.migrate_stage2 import migrate_database, copy_baseline, verify_baseline
from app.database import initialize


def create_question(client, headers, kind='number', key=None, title='你的年龄'):
    content = content_of(question('source', kind, title is not None))
    content['title'] = title
    body = {'name': title, 'content': content, 'request_key': key or str(uuid4())}
    response = client.post('/api/question-series', headers=headers, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json(), body


def reference(version, qid='age', rules=None):
    return {'id': qid, **deepcopy(version['content']), 'series_id': version['series_id'],
            'version_id': version['_id'], 'jump_rules': rules or []}


def other_headers(client):
    client.post('/api/auth/register', json={'username': 'Other', 'password': 'password123'})
    token = client.post('/api/auth/login', json={'username': 'Other', 'password': 'password123'}).json()['access_token']
    return {'Authorization': 'Bearer ' + token}


def edit_version(client, headers, sid, parent, content, key=None):
    result = client.post(f'/api/question-series/{sid}/versions', headers=headers,
                         json={'parent_version_id': parent, 'content': content, 'request_key': key or str(uuid4())})
    assert result.status_code in (200, 201), result.text
    return result.json()


def test_create_retry_and_invalid_content(client, headers):
    made, body = create_question(client, headers)
    repeated = client.post('/api/question-series', headers=headers, json=body)
    assert repeated.status_code == 200
    assert repeated.json()['version']['_id'] == made['version']['_id']
    changed = deepcopy(body); changed['content']['title'] = '不同题干'
    assert client.post('/api/question-series', headers=headers, json=changed).status_code == 409
    assert client.app.state.db.question_series.count_documents({}) == 1
    assert client.app.state.db.question_versions.count_documents({}) == 1
    for bad in ({**body, 'owner_id': str(ObjectId())}, {**body, 'request_key': 'bad'}):
        assert client.post('/api/question-series', headers=headers, json=bad).status_code == 422
    bad = deepcopy(body); bad['request_key'] = str(uuid4()); bad['content']['jump_rules'] = []
    assert client.post('/api/question-series', headers=headers, json=bad).status_code == 422
    assert client.get('/api/question-series', headers=headers).json()['total'] == 1


def test_branch_restore_and_immutable_old_survey(client, headers):
    made, _ = create_question(client, headers)
    sid, v1 = made['series']['_id'], made['version']
    survey = publish(client, headers, [reference(v1)], allow_repeat=True)
    submit = client.post('/api/fill/' + survey['share_code'] + '/submit', headers=headers,
                         json={'submission_key': str(uuid4()), 'answers': [{'question_id': 'age', 'value': 0}]})
    assert submit.status_code == 200
    first = client.get(f"/api/surveys/{survey['_id']}/statistics", headers=headers).json()
    content = deepcopy(v1['content']); content['title'] = '年龄 v2'
    v2 = edit_version(client, headers, sid, v1['_id'], content)
    content['title'] = '从 v1 分支'
    v3 = edit_version(client, headers, sid, v1['_id'], content)
    body = {'base_version_id': v3['_id'], 'restore_version_id': v1['_id'], 'request_key': str(uuid4())}
    restored = client.post(f'/api/question-series/{sid}/restorations', headers=headers, json=body).json()
    assert restored['version_no'] == 4
    assert restored['parent_version_id'] == v3['_id']
    assert restored['restored_from_version_id'] == v1['_id']
    assert restored['content'] == v1['content']
    assert client.post(f'/api/question-series/{sid}/restorations', headers=headers, json=body).json()['_id'] == restored['_id']
    assert v2['parent_version_id'] == v3['parent_version_id'] == v1['_id']
    unchanged = client.get(f"/api/surveys/{survey['_id']}", headers=headers).json()
    assert unchanged['questions'] == survey['questions']
    assert client.get(f"/api/surveys/{survey['_id']}/statistics", headers=headers).json() == first
    assert client.get('/api/question-versions/' + v1['_id'], headers=headers).json()['content'] == v1['content']
    assert client.put('/api/question-versions/' + v1['_id'], headers=headers, json={'content': content}).status_code == 405
    assert client.put(f"/api/surveys/{survey['_id']}", headers=headers, json=payload([reference(v2)])).status_code == 409


def test_reference_reuse_tampering_and_ownership(client, headers):
    made, _ = create_question(client, headers)
    version = made['version']
    a = client.post('/api/surveys', headers=headers, json=payload([reference(version, 'a')])).json()
    b = client.post('/api/surveys', headers=headers, json=payload([reference(version, 'b')])).json()
    assert a['questions'][0]['version_id'] == b['questions'][0]['version_id']
    assert client.get(f"/api/question-series/{made['series']['_id']}/usages", headers=headers).json()['visible_total'] == 2
    forged = reference(version); forged['title'] = '伪造快照'
    assert client.post('/api/surveys', headers=headers, json=payload([forged])).status_code == 422
    assert client.post('/api/surveys', headers=headers, json=payload([reference(version,'x'),reference(version,'y')])).status_code == 409
    other = other_headers(client)
    assert client.get('/api/question-versions/' + version['_id'], headers=other).status_code == 404
    assert client.post('/api/surveys', headers=other, json=payload([reference(version)])).status_code == 404
    assert client.get('/api/question-series', headers=other).json()['total'] == 0
    fill_survey = publish(client, headers, [reference(version)])
    public = client.get('/api/fill/' + fill_survey['share_code'], headers=other).json()
    assert 'version_id' not in public['questions'][0] and 'series_id' not in public['questions'][0]


def test_archive_preserves_old_binding_but_blocks_new_use(client, headers):
    made, _ = create_question(client, headers)
    sid, version = made['series']['_id'], made['version']
    survey = client.post('/api/surveys', headers=headers, json=payload([reference(version)])).json()
    assert client.patch(f'/api/question-series/{sid}', headers=headers, json={'status': 'archived'}).status_code == 200
    assert client.post('/api/surveys', headers=headers, json=payload([reference(version)])).status_code == 409
    retained = client.put(f"/api/surveys/{survey['_id']}", headers=headers, json=payload(survey['questions'], title='保留旧题'))
    assert retained.status_code == 200
    assert client.post(f"/api/surveys/{survey['_id']}/publish", headers=headers).status_code == 200
    assert client.get('/api/question-series', headers=headers).json()['total'] == 0
    assert client.get('/api/question-series?status=archived', headers=headers).json()['total'] == 1
    changed = deepcopy(version['content']); changed['title'] = '新题干'
    assert client.post(f'/api/question-series/{sid}/versions', headers=headers,
                       json={'parent_version_id': version['_id'], 'content': changed, 'request_key': str(uuid4())}).status_code == 409


def test_stale_save_and_legacy_body_cannot_remove_reference(client, headers):
    survey = client.post('/api/surveys', headers=headers, json=payload([question('q1')])).json()
    original_version = survey['questions'][0]['version_id']
    body = payload(engine_questions(survey['questions']), expected_updated_at=survey['updated_at'])
    same = client.put(f"/api/surveys/{survey['_id']}", headers=headers, json=body)
    assert same.status_code == 200
    assert same.json()['questions'][0]['version_id'] == original_version
    assert client.put(f"/api/surveys/{survey['_id']}", headers=headers, json=body).status_code == 409
    body.pop('expected_updated_at'); body['questions'][0]['title'] = '修改后题干'
    edited = client.put(f"/api/surveys/{survey['_id']}", headers=headers, json=body)
    assert edited.status_code == 200
    q = edited.json()['questions'][0]
    assert q['series_id'] == survey['questions'][0]['series_id'] and q['version_id'] != original_version
    assert client.put(f"/api/surveys/{survey['_id']}", headers=headers, json=body).json()['questions'][0]['version_id'] == q['version_id']


def test_replace_version_revalidates_jump_rules(client, headers):
    made, _ = create_question(client, headers, 'single')
    v1, sid = made['version'], made['series']['_id']
    rule = [{'id':'r1','operator':'eq','value':'a','target_question_id':'end'}]
    survey = client.post('/api/surveys', headers=headers, json=payload([reference(v1,'start',rule),question('end')])).json()
    changed = deepcopy(v1['content']); changed['options'] = changed['options'][1:]
    v2 = edit_version(client, headers, sid, v1['_id'], changed)
    qs = deepcopy(survey['questions']); qs[0] = reference(v2,'start',rule)
    url = f"/api/surveys/{survey['_id']}"
    assert client.put(url, headers=headers, json=payload(qs)).status_code == 422
    assert client.get(url, headers=headers).json()['questions'][0]['version_id'] == v1['_id']
    qs[0]['jump_rules'] = []
    saved = client.put(url, headers=headers, json=payload(qs))
    assert saved.status_code == 200 and saved.json()['questions'][0]['id'] == 'start'


def test_concurrent_retries_and_distinct_versions(client, headers):
    made, body = create_question(client, headers)
    # 首次创建的并发重试只产生一个成功系列。
    new_body = {**body, 'request_key': str(uuid4())}
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: client.post('/api/question-series',headers=headers,json=new_body),range(5)))
    assert all(r.status_code in (200,201) for r in results), [r.text for r in results]
    assert len({r.json()['series']['_id'] for r in results}) == 1
    assert client.app.state.db.question_series.count_documents({}) == 2
    sid, v1 = made['series']['_id'], made['version']
    def edit(i):
        content = deepcopy(v1['content']); content['title'] = f'并发版本 {i}'
        return client.post(f'/api/question-series/{sid}/versions',headers=headers,
                           json={'parent_version_id': v1['_id'],'content':content,'request_key':str(uuid4())})
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(edit, range(5)))
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert len({r.json()['version_no'] for r in results}) == 5
    changed = deepcopy(v1['content']); changed['title'] = '同一版本请求并发重试'
    body = {'parent_version_id':v1['_id'],'content':changed,'request_key':str(uuid4())}
    with ThreadPoolExecutor(max_workers=5) as pool:
        repeated = list(pool.map(lambda _:client.post(f'/api/question-series/{sid}/versions',headers=headers,json=body),range(5)))
    assert all(r.status_code in (200,201) for r in repeated), [r.text for r in repeated]
    assert len({r.json()['_id'] for r in repeated}) == 1
    assert client.app.state.db.question_versions.count_documents({'series_id':ObjectId(sid)}) == 7


def test_migrate_preserves_answers_and_repeated_apply(client, headers):
    survey = publish(client, headers, [question('q1','number',True)])
    assert client.post('/api/fill/' + survey['share_code'] + '/submit', headers=headers,
                       json={'submission_key':str(uuid4()),'answers':[{'question_id':'q1','value':0}]}).status_code == 200
    db = client.app.state.db
    old = db.surveys.find_one({'_id':ObjectId(survey['_id'])})
    old['schema_version']=1;old['questions']=engine_questions(old['questions'])
    db.surveys.replace_one({'_id':old['_id']},old)
    original_response = list(db.responses.find({}))
    baseline = client.get(f"/api/surveys/{survey['_id']}/statistics",headers=headers).json()
    before = db.question_versions.count_documents({})
    assert migrate_database(db)['legacy_questions'] == 1
    assert db.question_versions.count_documents({}) == before
    assert migrate_database(db,True)['migrated_surveys'] == 1
    migrated = db.surveys.find_one({'_id':old['_id']})
    assert migrated['updated_at'] == old['updated_at']
    assert engine_questions(migrated['questions']) == old['questions']
    assert list(db.responses.find({})) == original_response
    assert client.get(f"/api/surveys/{survey['_id']}/statistics",headers=headers).json() == baseline
    count = db.question_versions.count_documents({})
    assert migrate_database(db,True)['migrated_surveys'] == 0
    assert db.question_versions.count_documents({}) == count


def test_database_enforces_bound_schema_and_version_shape(client, headers):
    made, _ = create_question(client, headers)
    survey = client.post('/api/surveys',headers=headers,json=payload([reference(made['version'])])).json()
    db = client.app.state.db
    with pytest.raises(WriteError):
        db.surveys.update_one({'_id':ObjectId(survey['_id'])},{'$unset':{'questions.0.version_id':''}})
    with pytest.raises(WriteError):
        db.question_versions.insert_one({'series_id':ObjectId(),'content':{}})


def test_copy_baseline_only_to_empty_target_and_verify(client, headers):
    made = publish(client,headers,[question('q1')])
    source = client.app.state.db
    old = source.surveys.find_one({'_id':ObjectId(made['_id'])})
    old['questions']=engine_questions(old['questions']);old['schema_version']=1
    source.surveys.replace_one({'_id':old['_id']},old)
    name = source.name + '_copy'
    target = source.client[name]
    try:
        assert name.startswith('questionnaire_test_')
        # 预览只读，目标库不产生任何集合。
        assert copy_baseline(source.client,source.name,target)['surveys'] == 1
        assert target.list_collection_names() == []
        initialize(target)
        copy_baseline(source.client,source.name,target,True)
        migrate_database(target,True)
        assert verify_baseline(source,target) == {'users':1,'surveys':1,'responses':0}
        assert source.surveys.find_one({'_id':old['_id']}) == old
        with pytest.raises(BusinessError):
            copy_baseline(source.client,source.name,target,True)
    finally:
        source.client.drop_database(name)


def test_interrupted_legacy_save_reuses_version(client, headers, monkeypatch):
    survey = client.post('/api/surveys',headers=headers,json=payload([question('q1')])).json()
    db = client.app.state.db
    body = payload(engine_questions(survey['questions']))
    body['questions'][0]['title'] = '中断后应复用的版本'
    # 模拟版本已插入，但问卷条件更新发生冲突。
    original_update = type(db.surveys).update_one
    class Missed:
        matched_count = 0
    with monkeypatch.context() as patch:
        patch.setattr(type(db.surveys),'update_one',lambda self,*args,**kwargs: Missed() if self.name=='surveys' else original_update(self,*args,**kwargs))
        response = client.put(f"/api/surveys/{survey['_id']}",headers=headers,json=body)
        assert response.status_code == 409
    versions_after_failure = db.question_versions.count_documents({})
    assert versions_after_failure == 2
    response = client.put(f"/api/surveys/{survey['_id']}",headers=headers,json=body)
    assert response.status_code == 200,response.text
    assert db.question_versions.count_documents({}) == versions_after_failure
