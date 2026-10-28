"""仅操作本次明确命名的本机验收数据；用于原生确认框的接口辅助及只读核对。"""
import json
import os
import sys
from pathlib import Path
import httpx

BASE = 'http://127.0.0.1:8001/api'
SERIES = '98566236c17a406fa6ff36f3'
V1 = '6ada3bf2352e6b68ed47eb4a'
V2 = '6ada3ead352e6b68ed47eb56'
A = '6ada3c3d352e6b68ed47eb4e'
B = '6ada3d21352e6b68ed47eb4f'
C = '6ada3d90352e6b68ed47eb51'
BANK = '6ada3d2d352e6b68ed47eb50'
FORK = '27cda7efccc050b848ad0447'


def main():
    password = os.environ['ACCEPTANCE_PASSWORD']
    client = httpx.Client(base_url=BASE, timeout=10)

    def login(name):
        r = client.post('/auth/login', json={'username': name, 'password': password})
        r.raise_for_status()
        result = r.json()
        assert result['user']['username'] == name
        return {'Authorization': 'Bearer ' + result['access_token']}, result['user']

    ah, au = login('验收甲1023')
    bh, bu = login('验收乙1023')

    def call(method, path, headers, data=None):
        r = client.request(method, path, headers=headers, json=data)
        r.raise_for_status()
        return r.json()

    ad = call('GET', '/surveys/' + A, ah)
    bd = call('GET', '/surveys/' + B, bh)
    cd = call('GET', '/surveys/' + C, bh)
    assert ad['title'] == '验收_A_原始问卷'
    assert bd['title'] == '验收_B_共享复用'
    assert cd['title'] == '验收_C_版本更新'
    assert ad['questions'][0]['version_id'] == bd['questions'][0]['version_id'] == V1
    assert cd['questions'][0]['version_id'] == V2
    qid = bd['questions'][0]['id']
    action = sys.argv[1]
    result = {'action': action}
    if action == 'revoke_statistics':
        call('DELETE', f'/surveys/{B}/questions/{qid}/statistic-grants/{au["id"]}', bh)
        stats = call('GET', '/question-statistics/versions/' + V1, ah)
        assert stats['answered'] == 2 and stats['average'] == 10
        assert stats['source_survey_count'] == 1
        result['after_revoke'] = {'answered': stats['answered'], 'average': stats['average']}
    elif action == 'revoke_share':
        call('DELETE', f'/question-series/{SERIES}/shares/{bu["id"]}', ah)
        assert call('GET', '/question-series?scope=shared', bh)['total'] == 0
        fork = call('GET', '/question-series/' + FORK, bh)
        assert fork['forked_from'] is None and fork['forked_from_version_id'] == V2
        bank = call('GET', '/question-banks/' + BANK, bh)
        assert bank['items'][0]['version_id'] == V2
        assert bank['items'][0]['actions']['can_select'] is False
        result['retained_fork_and_bank_snapshot'] = True
    elif action == 'archive_restore':
        call('PATCH', '/question-series/' + SERIES, ah, {'status': 'archived'})
        detail = call('GET', '/question-series/' + SERIES, ah)
        assert detail['actions']['can_select'] is False and detail['version_count'] == 3
        stats = call('GET', '/surveys/' + A + '/statistics', ah)
        assert stats['total_responses'] == 2 and stats['questions'][0]['average'] == 10
        call('PATCH', '/question-series/' + SERIES, ah, {'status': 'active'})
        result['archived_history_and_answers_preserved'] = True
    elif action == 'remove_bank':
        bank = call('GET', '/question-banks/' + BANK, bh)
        assert bank['name'] == '验收_常用题库'
        empty = call('PUT', '/question-banks/' + BANK, bh,
                     {'name': bank['name'], 'description': bank['description'],
                      'version_ids': [], 'revision': bank['revision']})
        assert empty['items'] == []
        call('DELETE', '/question-banks/' + BANK, bh, {'revision': empty['revision']})
        assert call('GET', '/question-banks', bh)['total'] == 0
        result['removed_member_and_deleted_only_test_bank'] = True
    elif action == 'close_b':
        closed = call('POST', '/surveys/' + B + '/close', bh)
        assert closed['status'] == 'closed'
        result['status'] = 'closed'
    elif action != 'verify':
        raise ValueError('未知操作')

    result['surveys'] = []
    for sid, headers in ((A, ah), (B, bh), (C, bh)):
        detail = call('GET', '/surveys/' + sid, headers)
        stats = call('GET', '/surveys/' + sid + '/statistics', headers)
        result['surveys'].append({'id': sid, 'title': detail['title'], 'status': detail['status'],
                                  'version_id': detail['questions'][0]['version_id'],
                                  'responses': stats['total_responses'],
                                  'average': stats['questions'][0]['average']})
    if action == 'verify':
        assert [s['responses'] for s in result['surveys']] == [2, 1, 1]
        assert [s['average'] for s in result['surveys']] == [10, 40, 60]
        cross = [call('GET', '/question-statistics/versions/' + vid, bh) for vid in (V1, V2)]
        assert [(x['answered'], x['average']) for x in cross] == [(1, 40), (1, 60)]
        versions = call('GET', '/question-series/' + SERIES + '/versions', ah)['items']
        assert [v['version_no'] for v in versions] == [3, 2, 1]
        assert versions[0]['restored_from_version_id'] == V1
        assert versions[0]['parent_version_id'] == V2
        result['versions'] = [{'version_no': v['version_no'], 'operation': v['operation']} for v in versions]
        result['separate_version_statistics'] = [{'version_no': x['version']['version_no'],
                                                 'answered': x['answered'], 'average': x['average']} for x in cross]
    result['passed'] = True
    output = Path(__file__).parent / '验收记录'
    output.mkdir(exist_ok=True)
    (output / (action + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
