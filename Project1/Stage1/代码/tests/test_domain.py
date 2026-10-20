import pytest
from app.domain import configure_questions, evaluate, OPERATORS
from app.errors import BusinessError
from conftest import question


@pytest.mark.parametrize('operator,value,condition,expected', [
    ('eq', 1, 1, True), ('ne', 1, 2, True), ('gt', 3, 3, False),
    ('gte', 3, 3, True), ('lt', 2, 3, True), ('lte', 3, 3, True),
    ('between', 18, {'min': 18, 'max': 60}, True),
    ('contains_any', ['a', 'c'], ['a', 'b'], True),
    ('contains_all', ['a', 'b', 'c'], ['a', 'b'], True),
    ('contains_all', ['a'], ['a', 'b'], False),
    ('exact_set', ['b', 'a'], ['a', 'b'], True),
    ('exact_set', ['a', 'b', 'c'], ['a', 'b'], False),
])
def test_operators(operator, value, condition, expected):
    assert OPERATORS[operator](value, condition) is expected


@pytest.mark.parametrize('kind,config,value', [
    ('single', {}, 'missing'), ('multiple', {'min_choices': 2}, ['a']),
    ('multiple', {'max_choices': 1}, ['a', 'b']), ('multiple', {}, ['a', 'a']),
    ('multiple', {'exact_choices': 2}, ['a', 'b', 'c']),
    ('text', {'min_length': 2}, '一'), ('text', {'max_length': 2}, '三个字'),
    ('text', {'format': 'digits'}, ' 0123'), ('text', {'format': 'digits'}, '12.3'),
    ('text', {'format': 'digits'}, '１２３'), ('number', {'integer_only': True}, 1.5),
    ('number', {'min_value': 0}, -1), ('number', {'max_value': 120}, 121),
    ('number', {}, True), ('number', {}, '20'), ('number', {}, 10**100),
])
def test_invalid_answers(kind, config, value):
    questions = configure_questions([question('q1', kind, validation=config)])
    with pytest.raises(BusinessError):
        evaluate(questions, [{'question_id': 'q1', 'value': value}])


def test_skip_required_and_discard_old_branch():
    qs = configure_questions([
        question('q1', 'single', True, rules=[{'id': 'r1', 'operator': 'eq', 'value': 'a', 'target_question_id': 'q3'}]),
        question('q2', required=True), question('q3')])
    result = evaluate(qs, [{'question_id': 'q1', 'value': 'a'}, {'question_id': 'q2', 'value': '旧答案'}])
    assert result['path'] == ['q1', 'q3']
    assert result['answers'] == [{'question_id': 'q1', 'value': 'a'}]


def test_first_rule_wins():
    qs = configure_questions([
        question('q1', 'number', rules=[
            {'id': 'r1', 'operator': 'gt', 'value': 0, 'target_question_id': 'q3'},
            {'id': 'r2', 'operator': 'gt', 'value': 0, 'target_question_id': 'q4'}]),
        question('q2'), question('q3'), question('q4')])
    assert evaluate(qs, [{'question_id': 'q1', 'value': 1}])['path'] == ['q1', 'q3', 'q4']


def test_zero_unicode_and_phone():
    qs = configure_questions([question('q1', 'number', validation={'integer_only': True}),
                              question('q2', validation={'min_length': 2, 'max_length': 2}),
                              question('q3', validation={'format': 'digits'})])
    result = evaluate(qs, [{'question_id': 'q1', 'value': 0}, {'question_id': 'q2', 'value': ' 中😀 '},
                           {'question_id': 'q3', 'value': '00123'}])
    assert [a['value'] for a in result['answers']] == [0, '中😀', '00123']


@pytest.mark.parametrize('config', [{'min_choices': 3, 'max_choices': 1}, {'exact_choices': 2, 'min_choices': 1}])
def test_invalid_choice_config(config):
    with pytest.raises(BusinessError):
        configure_questions([question('q1', 'multiple', validation=config)])


def test_required_normalization_and_forward_only():
    qs = configure_questions([question('q1', 'multiple', validation={'min_choices': 1})])
    assert qs[0]['required'] is True
    with pytest.raises(BusinessError):
        configure_questions([question('q1', 'single', rules=[{'id':'r1','operator':'eq','value':'a','target_question_id':'q1'}])])


def test_partial_and_missing_required():
    qs = configure_questions([question('q1', required=True)])
    assert evaluate(qs, [], partial=True)['next_question_id'] == 'q1'
    with pytest.raises(BusinessError):
        evaluate(qs, [])
