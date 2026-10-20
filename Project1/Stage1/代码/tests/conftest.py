import os
import uuid
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    settings = Settings(mongo_uri=os.getenv('TEST_MONGO_URI', 'mongodb://127.0.0.1:27018'),
                        database='questionnaire_test_' + uuid.uuid4().hex,
                        jwt_secret='test-only-secret-with-at-least-thirty-two-characters')
    with TestClient(create_app(settings)) as c:
        yield c
        # 只删除本次随机生成的测试数据库，不影响正式数据。
        assert settings.database.startswith('questionnaire_test_')
        c.app.state.db.client.drop_database(settings.database)


@pytest.fixture
def headers(client):
    client.post('/api/auth/register', json={'username': 'Owner', 'password': 'password123'})
    data = client.post('/api/auth/login', json={'username': 'owner', 'password': 'password123'}).json()
    return {'Authorization': 'Bearer ' + data['access_token']}


def question(qid, kind='text', required=False, validation=None, rules=None):
    return {'id': qid, 'type': kind, 'title': qid, 'required': required,
            'options': [{'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}, {'id': 'c', 'label': 'C'}]
            if kind in ('single', 'multiple') else [],
            'validation': validation or {}, 'jump_rules': rules or []}


def payload(questions, **kwargs):
    return {'title': '测试问卷', 'description': '用于测试', 'questions': questions, **kwargs}


def publish(client, headers, questions, **kwargs):
    response = client.post('/api/surveys', json=payload(questions, **kwargs), headers=headers)
    assert response.status_code == 201, response.text
    survey = response.json()
    response = client.post('/api/surveys/' + survey['_id'] + '/publish', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()
