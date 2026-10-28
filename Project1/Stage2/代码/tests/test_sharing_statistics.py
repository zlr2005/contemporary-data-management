from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4
from bson import ObjectId
from pymongo.errors import WriteError
import pytest

from conftest import payload, question, publish
from test_question_versions import create_question, reference, edit_version, other_headers


def account(client, name):
    assert client.post('/api/auth/register', json={'username':name,'password':'password123'}).status_code == 201
    result = client.post('/api/auth/login',json={'username':name,'password':'password123'}).json()
    return {'Authorization':'Bearer '+result['access_token']}


def put(client, path, headers, body, expected=200):
    r = client.put('/api'+path,headers=headers,json=body)
    assert r.status_code == expected,r.text
    return r.json()


def grant(client, survey, qid, owner, username, content=False):
    return put(client,f"/surveys/{survey['_id']}/questions/{qid}/statistic-grants",owner,
               {'username':username,'allow_contents':content})


def submit(client, survey, headers, answers):
    r = client.post('/api/fill/'+survey['share_code']+'/submit',headers=headers,
                    json={'submission_key':str(uuid4()),'answers':[{'question_id':k,'value':v} for k,v in answers.items()]})
    assert r.status_code == 200,r.text


def stats(client, vid, headers, suffix=''):
    r=client.get('/api/question-statistics/versions/'+vid+suffix,headers=headers)
    assert r.status_code == 200,r.text
    return r.json()


def test_share_future_versions_and_owned_fork(client,headers):
    made,_=create_question(client,headers);sid=made['series']['_id'];v1=made['version']
    other=other_headers(client)
    share=put(client,f'/question-series/{sid}/shares',headers,{'username':' OTHER '})
    assert client.get('/api/question-series?scope=shared',headers=other).json()['total']==1
    changed=deepcopy(v1['content']);changed['title']='新版本题目'
    v2=edit_version(client,headers,sid,v1['_id'],changed)
    history=client.get(f'/api/question-series/{sid}/versions',headers=other).json()
    assert history['total']==2
    assert client.post(f'/api/question-series/{sid}/versions',headers=other,
        json={'parent_version_id':v1['_id'],'content':changed,'request_key':str(uuid4())}).status_code==404
    body={'name':'派生题','content':changed,'request_key':str(uuid4())}
    derived=client.post(f"/api/question-versions/{v2['_id']}/forks",headers=other,json=body)
    assert derived.status_code==201,derived.text
    fork=derived.json()
    assert fork['series']['forked_from_version_id']==v2['_id']
    assert fork['series']['forked_from']['version_no']==2
    assert fork['series']['owner_id']==share['grantee_id'] and fork['series']['_id']!=sid
    assert client.post(f"/api/question-versions/{v2['_id']}/forks",headers=other,json=body).json()['version']['_id']==fork['version']['_id']
    assert client.patch(f'/api/question-series/{sid}',headers=other,json={'name':'覆盖'}).status_code==404
    client.delete(f"/api/question-series/{sid}/shares/{share['grantee_id']}",headers=headers)
    private_fork=client.get('/api/question-series/'+fork['series']['_id'],headers=other).json()
    assert private_fork['forked_from'] is None and private_fork['forked_from_version_id']==v2['_id']


def test_revoked_share_preserves_existing_surveys_but_blocks_new_references(client,headers):
    made,_=create_question(client,headers);sid=made['series']['_id'];v=made['version'];other=other_headers(client)
    shared=put(client,f'/question-series/{sid}/shares',headers,{'username':'Other'})
    survey=client.post('/api/surveys',headers=other,json=payload([reference(v)])).json()
    path=f"/api/question-series/{sid}/shares/{shared['grantee_id']}"
    assert client.delete(path,headers=headers).status_code==200
    assert client.delete(path,headers=headers).status_code==200
    assert client.get(f'/api/question-series/{sid}/versions',headers=other).status_code==404
    assert client.get('/api/question-series?scope=shared',headers=other).json()['total']==0
    assert client.post('/api/surveys',headers=other,json=payload([reference(v)])).status_code==404
    retained=client.get(f"/api/surveys/{survey['_id']}",headers=other)
    assert retained.status_code==200 and retained.json()['question_bindings'][0]['source_status']=='revoked'
    assert client.put(f"/api/surveys/{survey['_id']}",headers=other,json=payload(survey['questions'],title='保持引用')).status_code==200
    clone=[reference(v,'another')]
    assert client.put(f"/api/surveys/{survey['_id']}",headers=other,json=payload(clone)).status_code==404
    assert client.post(f"/api/surveys/{survey['_id']}/publish",headers=other).status_code==200
    submit(client,survey,other,{'age':0})
    assert client.get(f"/api/surveys/{survey['_id']}/statistics",headers=other).json()['questions'][0]['average']==0
    assert client.get(f'/api/question-series/{sid}/usages',headers=other).json()['visible_total']==1
    assert client.post(f"/api/question-versions/{v['_id']}/forks",headers=other,
        json={'name':'禁止派生','content':v['content'],'request_key':str(uuid4())}).status_code==404


def test_share_validation_concurrent_upsert_and_regrant(client,headers):
    made,_=create_question(client,headers);sid=made['series']['_id'];other=other_headers(client)
    assert client.put(f'/api/question-series/{sid}/shares',headers=other,json={'username':'owner'}).status_code==404
    for name in ('Owner','NotRegistered'):
        assert client.put(f'/api/question-series/{sid}/shares',headers=headers,json={'username':name}).status_code==422
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:client.put(f'/api/question-series/{sid}/shares',headers=headers,json={'username':'other'}),range(4)))
    assert all(r.status_code==200 for r in results),[r.text for r in results]
    assert client.app.state.db.question_shares.count_documents({})==1
    old=results[0].json()
    client.delete(f"/api/question-series/{sid}/shares/{old['grantee_id']}",headers=headers)
    new=put(client,f'/question-series/{sid}/shares',headers,{'username':'Other'})
    assert new['_id']==old['_id'] and new['created_at']==old['created_at'] and new['status']=='active'


def test_bank_revisions_versions_and_delete_preserve_questions(client,headers):
    made,_=create_question(client,headers);sid=made['series']['_id'];v1=made['version']
    changed=deepcopy(v1['content']);changed['title']='新的内容';v2=edit_version(client,headers,sid,v1['_id'],changed)
    bank=client.post('/api/question-banks',headers=headers,json={'name':'题库','description':'说明'}).json();bid=bank['_id']
    body={'name':'题库','description':'说明','version_ids':[v1['_id'],v2['_id']],'revision':bank['revision']}
    saved=put(client,f'/question-banks/{bid}',headers,body)
    assert [i['version_id'] for i in saved['items']]==[v1['_id'],v2['_id']]
    assert client.put(f'/api/question-banks/{bid}',headers=headers,json=body).status_code==409
    duplicate={**body,'revision':saved['revision'],'version_ids':[v1['_id'],v1['_id']]}
    assert client.put(f'/api/question-banks/{bid}',headers=headers,json=duplicate).status_code==409
    other=other_headers(client)
    for method in ('get','put','delete'):
        kwargs={} if method=='get' else {'json':body if method=='put' else {'revision':saved['revision']}}
        assert client.request(method.upper(),f'/api/question-banks/{bid}',headers=other,**kwargs).status_code==404
    assert client.request('DELETE',f'/api/question-banks/{bid}',headers=headers,json={'revision':bank['revision']}).status_code==409
    assert client.request('DELETE',f'/api/question-banks/{bid}',headers=headers,json={'revision':saved['revision']}).status_code==200
    assert client.get('/api/question-versions/'+v1['_id'],headers=headers).status_code==200


def test_bank_cancelled_shares_keep_snapshots_without_new_usage(client,headers):
    made,_=create_question(client,headers);sid=made['series']['_id'];v=made['version'];other=other_headers(client)
    shared=put(client,f'/question-series/{sid}/shares',headers,{'username':'Other'})
    bank=client.post('/api/question-banks',headers=other,json={'name':'共享题库'}).json();bid=bank['_id']
    saved=put(client,f'/question-banks/{bid}',other,{'name':'共享题库','description':'','version_ids':[v['_id']],'revision':bank['revision']})
    client.delete(f"/api/question-series/{sid}/shares/{shared['grantee_id']}",headers=headers)
    current=client.get(f'/api/question-banks/{bid}',headers=other).json()
    assert current['items'][0]['content']==v['content']
    assert current['items'][0]['actions']['can_select'] is False
    kept=put(client,f'/question-banks/{bid}',other,{'name':'仍可保留','description':'','version_ids':[v['_id']],'revision':saved['revision']})
    empty=put(client,f'/question-banks/{bid}',other,{'name':'移出','description':'','version_ids':[],'revision':kept['revision']})
    assert client.put(f'/api/question-banks/{bid}',headers=other,json={'name':'禁止重新加入','description':'','version_ids':[v['_id']],'revision':empty['revision']}).status_code==404


def test_cross_statistics_pair_matching_permissions_and_content_scope(client,headers):
    made,_=create_question(client,headers);v=made['version'];sid=made['series']['_id'];other=other_headers(client)
    unrelated,_=create_question(client,headers,title='其他数字题');w=unrelated['version']
    for series in (sid,unrelated['series']['_id']):put(client,f'/question-series/{series}/shares',headers,{'username':'Other'})
    a=publish(client,headers,[reference(v,'a'),reference(w,'b')],allow_repeat=True,allow_anonymous=True)
    b=publish(client,other,[reference(v,'b'),reference(w,'a')],allow_repeat=True)
    submit(client,a,headers,{'a':0,'b':900});submit(client,a,headers,{'a':20,'b':901});submit(client,b,other,{'b':40,'a':999})
    before=stats(client,v['_id'],headers)
    assert before['answered']==2 and before['average']==10
    uses=client.get(f'/api/question-series/{sid}/usages',headers=headers).json()
    assert uses['visible_total']==1 and uses['restricted_survey_count']==1
    permission=grant(client,b,'b',other,'Owner')
    after=stats(client,v['_id'],headers)
    assert after['answered']==3 and after['average']==20 and after['total_responses']==3
    assert after['minimum']==0 and after['maximum']==40 and sum(i['count'] for i in after['distribution'])==3
    assert after['content_access']['answered']==2 and after['content_access']['partial'] is True
    assert stats(client,v['_id'],headers,'?scope=own')['average']==10
    assert stats(client,v['_id'],headers,'?scope=authorized')['average']==40
    contents=stats(client,v['_id'],headers,'/contents')
    assert contents['total']==2 and {i['value'] for i in contents['items']}=={0,20}
    assert all(set(item)=={'value'} for item in contents['items'])
    sources=stats(client,v['_id'],headers,'/sources')
    assert sources['total']==2 and all('share_code' not in i and 'owner_id' not in i for i in sources['items'])
    visible=client.get(f'/api/question-series/{sid}/usages',headers=headers).json()
    assert visible['visible_total']==2 and any(i['owner_context']=='statistics_only' for i in visible['visible_items'])
    grant(client,b,'b',other,'Owner',True)
    assert stats(client,v['_id'],headers,'/contents')['total']==3
    client.delete(f"/api/surveys/{b['_id']}/questions/b/statistic-grants/{permission['grantee_id']}",headers=other)
    assert stats(client,v['_id'],headers)['answered']==2


def test_statistic_grant_only_does_not_open_series_or_whole_survey(client,headers):
    made,_=create_question(client,headers,'text');v=made['version'];sid=made['series']['_id'];analyst=account(client,'Analyst')
    survey=publish(client,headers,[reference(v)],allow_anonymous=True)
    submit(client,survey,headers,{'age':'00123'})
    permission=grant(client,survey,'age',headers,'Analyst')
    changed=deepcopy(v['content']);changed['title']='未授权的另一个版本';v2=edit_version(client,headers,sid,v['_id'],changed)
    listing=client.get('/api/question-statistics/versions',headers=analyst).json()
    assert {i['_id'] for i in listing['items']}=={v['_id']}
    assert client.get('/api/question-versions/'+v['_id'],headers=analyst).status_code==404
    for endpoint in ('','/statistics','/responses'):
        assert client.get(f"/api/surveys/{survey['_id']}{endpoint}",headers=analyst).status_code==404
    assert client.get('/api/question-statistics/versions/'+v2['_id'],headers=analyst).status_code==404
    base=stats(client,v['_id'],analyst);assert base['answered']==1
    assert 'created_by' not in base['version']
    assert stats(client,v['_id'],analyst,'/contents')['total']==0
    grant(client,survey,'age',headers,'Analyst',True)
    assert stats(client,v['_id'],analyst,'/contents')['items']==[{'value':'00123'}]
    client.delete(f"/api/surveys/{survey['_id']}/questions/age/statistic-grants/{permission['grantee_id']}",headers=headers)
    assert client.get('/api/question-statistics/versions/'+v['_id'],headers=analyst).status_code==404
    assert client.get('/api/question-statistics/versions',headers=analyst).json()['total']==0


@pytest.mark.parametrize('boundaries',[[0],[10,10],[20,10],[0,1e16],['nan','inf']])
def test_invalid_distribution_boundaries(client,headers,boundaries):
    made,_=create_question(client,headers);vid=made['version']['_id']
    result=client.get('/api/question-statistics/versions/'+vid,headers=headers,params=[('boundaries',x) for x in boundaries])
    assert result.status_code==422,result.text


def test_distribution_boundaries_and_empty_constant_values(client,headers):
    made,_=create_question(client,headers);v=made['version']
    survey=publish(client,headers,[reference(v)],allow_repeat=True)
    assert stats(client,v['_id'],headers)['average'] is None
    assert stats(client,v['_id'],headers)['distribution']==[]
    submit(client,survey,headers,{'age':0})
    assert stats(client,v['_id'],headers)['distribution']==[{'min':0,'max':0,'include_min':True,'include_max':True,'count':1}]
    for n in (-10,10,20):submit(client,survey,headers,{'age':n})
    r=stats(client,v['_id'],headers,'?boundaries=0&boundaries=10')
    assert [i['count'] for i in r['distribution']]==[1,1,2]
    assert r['answered']==4 and r['average']==5


@pytest.mark.parametrize('kind,values,counts',[('single',['a','b','a'],[2,1,0]),('multiple',[['a','b'],['b','c']],[1,2,1])])
def test_cross_choice_counts(client,headers,kind,values,counts):
    made,_=create_question(client,headers,kind);v=made['version']
    survey=publish(client,headers,[reference(v)],allow_repeat=True)
    for value in values:submit(client,survey,headers,{'age':value})
    result=stats(client,v['_id'],headers)
    assert [o['count'] for o in result['options']]==counts
    assert result['answered']==len(values)
    assert client.get('/api/question-statistics/versions/'+v['_id']+'/contents',headers=headers).status_code==422


def test_grants_require_published_question_and_strict_input(client,headers):
    made,_=create_question(client,headers,'single');v=made['version'];other=other_headers(client)
    draft=client.post('/api/surveys',headers=headers,json=payload([reference(v)])).json()
    url=f"/api/surveys/{draft['_id']}/questions/age/statistic-grants"
    assert client.put(url,headers=headers,json={'username':'Other'}).status_code==409
    client.post(f"/api/surveys/{draft['_id']}/publish",headers=headers)
    assert client.put(url,headers=headers,json={'username':'Other','allow_contents':True}).status_code==422
    assert client.put(url,headers=other,json={'username':'owner'}).status_code==404
    assert client.put(url,headers=headers,json={'username':'Other','version_id':v['_id']}).status_code==422
    with pytest.raises(WriteError):client.app.state.db.statistic_grants.insert_one({'survey_id':ObjectId()})


def test_archived_shared_source_and_shared_legacy_edit(client,headers):
    made,_=create_question(client,headers);sid=made['series']['_id'];v=made['version'];other=other_headers(client)
    put(client,f'/question-series/{sid}/shares',headers,{'username':'Other'})
    survey=client.post('/api/surveys',headers=other,json=payload([reference(v)])).json()
    legacy=[{k:val for k,val in survey['questions'][0].items() if k not in ('series_id','version_id')}]
    legacy[0]['title']='通过旧接口派生'
    changed=client.put(f"/api/surveys/{survey['_id']}",headers=other,json=payload(legacy))
    assert changed.status_code==200,changed.text
    assert changed.json()['questions'][0]['series_id']!=sid
    client.patch(f'/api/question-series/{sid}',headers=headers,json={'status':'archived'})
    assert client.get('/api/question-versions/'+v['_id'],headers=other).status_code==404
    assert client.post('/api/surveys',headers=other,json=payload([reference(v)])).status_code==404
    assert client.get(f"/api/surveys/{survey['_id']}",headers=other).status_code==200


def test_archived_shared_reference_can_still_publish(client,headers):
    made,_=create_question(client,headers);sid=made['series']['_id'];v=made['version'];other=other_headers(client)
    put(client,f'/question-series/{sid}/shares',headers,{'username':'Other'})
    survey=client.post('/api/surveys',headers=other,json=payload([reference(v)])).json()
    client.patch(f'/api/question-series/{sid}',headers=headers,json={'status':'archived'})
    assert client.put(f"/api/surveys/{survey['_id']}",headers=other,json=payload(survey['questions'])).status_code==200
    assert client.post(f"/api/surveys/{survey['_id']}/publish",headers=other).status_code==200
    submit(client,survey,other,{'age':0})
    assert client.get(f"/api/surveys/{survey['_id']}/statistics",headers=other).json()['questions'][0]['average']==0


def test_concurrent_bank_updates_do_not_overwrite(client,headers):
    made,_=create_question(client,headers);v=made['version']
    bank=client.post('/api/question-banks',headers=headers,json={'name':'并发题库'}).json()
    def update(n):
        return client.put('/api/question-banks/'+bank['_id'],headers=headers,
            json={'name':f'编辑 {n}','description':'','version_ids':[v['_id']],'revision':bank['revision']})
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(update,range(2)))
    assert sorted(r.status_code for r in results)==[200,409]
    saved=client.get('/api/question-banks/'+bank['_id'],headers=headers).json()
    assert saved['revision']==2 and len(saved['items'])==1


@pytest.mark.parametrize('values',[[0,1e-323],[1e15-0.125,1e15]])
def test_numeric_distribution_at_float_precision_limits(client,headers,values):
    made,_=create_question(client,headers);v=made['version'];survey=publish(client,headers,[reference(v)],allow_repeat=True)
    for value in values:submit(client,survey,headers,{'age':value})
    result=stats(client,v['_id'],headers)
    assert sum(b['count'] for b in result['distribution'])==2
    assert all(b['min']<b['max'] for b in result['distribution'])


def test_stale_statistic_grant_cannot_open_another_version(client,headers):
    made,_=create_question(client,headers);v=made['version'];other=other_headers(client)
    survey=publish(client,headers,[reference(v)])
    changed=deepcopy(v['content']);changed['title']='另一个版本';v2=edit_version(client,headers,made['series']['_id'],v['_id'],changed)
    permission=grant(client,survey,'age',headers,'Other')
    client.app.state.db.statistic_grants.update_one({'_id':ObjectId(permission['_id'])},{'$set':{'version_id':ObjectId(v2['_id'])}})
    assert client.get('/api/question-statistics/versions',headers=other).json()['total']==0
    assert client.get('/api/question-statistics/versions/'+v2['_id'],headers=other).status_code==404
