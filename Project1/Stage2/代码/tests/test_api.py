from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from bson import ObjectId
import pytest
from pymongo.errors import WriteError
from conftest import question, payload, publish


def submit_data(value='回答', key=None):
    return {'submission_key': key or str(uuid4()), 'answers': [{'question_id': 'q1', 'value': value}]}


def test_auth_and_ownership(client, headers):
    assert client.post('/api/auth/register', json={'username':'OWNER','password':'password123'}).status_code == 409
    assert client.post('/api/auth/login', json={'username':'owner','password':'wrong-password'}).status_code == 401
    assert client.get('/api/surveys').status_code == 401
    created=client.post('/api/surveys', headers=headers, json=payload([question('q1')])).json()
    assert client.get('/api/surveys', headers=headers).json()['total'] == 1
    client.post('/api/auth/register', json={'username':'Other','password':'password123'})
    token=client.post('/api/auth/login', json={'username':'Other','password':'password123'}).json()['access_token']
    other={'Authorization':'Bearer '+token}
    assert client.get('/api/surveys', headers=other).json()['items'] == []
    for endpoint in ['', '/statistics', '/responses']:
        assert client.get(f"/api/surveys/{created['_id']}{endpoint}", headers=other).status_code == 404
    assert client.put(f"/api/surveys/{created['_id']}", headers=other,json=payload([])).status_code == 404


def test_creation_add_publish_and_lock(client, headers):
    survey=client.post('/api/surveys',headers=headers,json=payload([])).json()
    sid=survey['_id']
    assert client.post(f'/api/surveys/{sid}/publish',headers=headers).status_code == 422
    updated=client.put(f'/api/surveys/{sid}',headers=headers,json=payload([question('q1')]))
    assert updated.status_code == 200
    assert client.post(f'/api/surveys/{sid}/publish',headers=headers).status_code == 200
    assert client.put(f'/api/surveys/{sid}',headers=headers,json=payload([question('q1')])).status_code == 409
    assert client.patch(f'/api/surveys/{sid}',headers=headers,json={'title':'新标题','description':'','deadline_at':None}).status_code == 200


def test_submission_statistics_anonymity_and_retry(client, headers):
    survey=publish(client, headers, [question('q1','number',True),question('q2','text',validation={'format':'digits'})], allow_anonymous=True,allow_repeat=True)
    base='/api/fill/'+survey['share_code']
    data=submit_data(0); data['answers'].append({'question_id':'q2','value':'00123'})
    a=client.post(base+'/submit',headers=headers,json=data)
    assert a.status_code == 200,a.text
    b=client.post(base+'/submit',headers=headers,json=data)
    assert a.json()['response_id'] == b.json()['response_id']
    data['answers'][0]['value']=20
    assert client.post(base+'/submit',headers=headers,json=data).status_code == 409
    data['submission_key']=str(uuid4())
    assert client.post(base+'/submit',headers=headers,json=data).status_code == 200
    stats=client.get(f"/api/surveys/{survey['_id']}/statistics",headers=headers).json()
    assert stats['total_responses'] == 2
    assert stats['questions'][0]['average'] == 10
    contents=client.get(f"/api/surveys/{survey['_id']}/questions/q2/contents",headers=headers).json()
    assert contents['items'][0]['value'] == '00123'
    rows=client.get(f"/api/surveys/{survey['_id']}/responses",headers=headers).json()['items']
    assert all('respondent_id' not in r and 'submission_key' not in r for r in rows)
    assert 'respondent_id' not in client.get(base,headers=headers).text


def test_real_concurrent_unique_index(client, headers):
    survey=publish(client,headers,[question('q1')])
    url='/api/fill/'+survey['share_code']+'/submit'
    with ThreadPoolExecutor(max_workers=6) as executor:
        statuses=list(executor.map(lambda _:client.post(url,headers=headers,json=submit_data()).status_code,range(6)))
    assert statuses.count(200)==1,statuses
    assert statuses.count(409)==5,statuses
    db=client.app.state.db
    assert db.responses.count_documents({'survey_id':ObjectId(survey['_id'])}) == 1


def test_closed_expired_draft_and_preview(client,headers):
    draft=client.post('/api/surveys',headers=headers,json=payload([question('q1')])).json()
    assert client.get('/api/fill/'+draft['share_code'],headers=headers).status_code == 409
    assert client.post(f"/api/surveys/{draft['_id']}/preview",headers=headers,json={'answers':[]}).status_code == 200
    survey=publish(client,headers,[question('q1')])
    url='/api/fill/'+survey['share_code']+'/submit'
    client.patch(f"/api/surveys/{survey['_id']}",headers=headers,json={'title':'过期','description':'','deadline_at':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()})
    assert client.post(url,headers=headers,json=submit_data()).status_code == 409
    survey=publish(client,headers,[question('q1')])
    url='/api/fill/'+survey['share_code']+'/submit'
    data=submit_data()
    saved=client.post(url,headers=headers,json=data).json()
    client.post(f"/api/surveys/{survey['_id']}/close",headers=headers)
    assert client.post(url,headers=headers,json=submit_data()).status_code == 409
    assert client.post(url,headers=headers,json=data).json()['response_id']==saved['response_id']


def test_jump_and_choice_statistics(client,headers):
    qs=[question('q1','single',True,rules=[{'id':'r1','operator':'eq','value':'a','target_question_id':'q3'}]),
        question('q2',required=True),question('q3','multiple',validation={'min_choices':1,'max_choices':2})]
    survey=publish(client,headers,qs)
    data={'submission_key':str(uuid4()),'answers':[{'question_id':'q1','value':'a'}, {'question_id':'q2','value':'旧内容'}, {'question_id':'q3','value':['b','c']}]}
    url='/api/fill/'+survey['share_code']
    result=client.post(url+'/evaluate',headers=headers,json={'answers':data['answers']}).json()
    assert result['path']==['q1','q3']
    assert client.post(url+'/submit',headers=headers,json=data).status_code == 200
    stats=client.get(f"/api/surveys/{survey['_id']}/statistics",headers=headers).json()['questions']
    assert stats[0]['options'][0]['count']==1
    assert stats[0]['options'][1]['count']==0
    assert stats[1]['answered']==0
    assert [x['count'] for x in stats[2]['options']]==[0,1,1]
    assert len(client.get(f"/api/surveys/{survey['_id']}/statistics?question_id=q3",headers=headers).json()['questions'])==1


def test_validator_and_request_rejection(client,headers):
    with pytest.raises(WriteError):
        client.app.state.db.responses.insert_one({'survey_id':ObjectId(),'respondent_id':ObjectId()})
    assert client.post('/api/surveys',headers=headers,json={**payload([]),'owner_id':'forged'}).status_code==422
    assert client.get('/api/surveys/not-an-id',headers=headers).status_code==404
    assert client.get('/api/surveys?page=0',headers=headers).status_code==422


def test_pages_served(client):
    assert client.get('/').status_code==200
    assert client.get('/survey/example').status_code==200
    assert client.get('/static/app.js').status_code==200
    assert client.get('/api/health').json()['status']=='ok'
