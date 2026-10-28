"""与 HTTP、MongoDB 无关的规则引擎。扩展题型注册 Handler；扩展条件注册 Operator。"""
import math
import operator
import re
from copy import deepcopy
from .errors import BusinessError, require

OPERATORS = {
    'eq': operator.eq, 'ne': operator.ne, 'gt': operator.gt,
    'gte': operator.ge, 'lt': operator.lt, 'lte': operator.le,
    'between': lambda a, b: b['min'] <= a <= b['max'],
    'contains_any': lambda a, b: bool(set(a) & set(b)),
    'contains_all': lambda a, b: set(b) <= set(a),
    'exact_set': lambda a, b: set(a) == set(b),
}


def finite_number(value):
    return type(value) in (int, float) and abs(value) <= 1e15 and math.isfinite(value)


def bounds(config, low, high, integer=False, cap=None):
    for key in (low, high):
        v = config.get(key)
        if v is not None:
            require(finite_number(v), f'{key} 必须为有限数字')
            if integer:
                require(type(v) is int and v >= 0, f'{key} 必须为非负整数')
            if cap is not None:
                require(v <= cap, f'{key} 不能大于 {cap}')
    a, b = config.get(low), config.get(high)
    require(a is None or b is None or a <= b, '最小限制不能大于最大限制')


class QuestionHandler:
    validation_keys = set()
    operators = set()

    def configure(self, q):
        require(not q['options'], '填空题不能配置选项')

    def normalize(self, q, value):
        return value


class ChoiceHandler(QuestionHandler):
    def configure(self, q):
        require(2 <= len(q['options']) <= 50, '选择题需要 2～50 个选项')

    def normalize(self, q, value):
        require(type(value) is str and value in {o['id'] for o in q['options']}, '请选择有效选项')
        return value


class SingleHandler(ChoiceHandler):
    operators = {'eq'}


class MultipleHandler(ChoiceHandler):
    validation_keys = {'min_choices', 'max_choices', 'exact_choices'}
    operators = {'contains_any', 'contains_all', 'exact_set'}

    def configure(self, q):
        super().configure(q)
        c = q['validation']
        bounds(c, 'min_choices', 'max_choices', True, len(q['options']))
        exact = c.get('exact_choices')
        if exact is not None:
            require(type(exact) is int and 0 <= exact <= len(q['options']), '恰好选择数量无效')
            require(c.get('min_choices') is None and c.get('max_choices') is None,
                    '恰好选择不能与最少、最多数量同时设置')
        if (c.get('min_choices') or 0) > 0 or (exact or 0) > 0:
            q['required'] = True
        require(not q['required'] or (exact != 0 and c.get('max_choices') != 0), '必答题不能限制为选择 0 个')

    def normalize(self, q, value):
        require(type(value) is list and all(type(x) is str for x in value), '多选答案必须为选项列表')
        require(len(value) == len(set(value)), '选项不能重复')
        require(set(value) <= {o['id'] for o in q['options']}, '包含无效选项')
        c, n = q['validation'], len(value)
        for key, check, text in [('min_choices', operator.ge, '至少'), ('max_choices', operator.le, '最多'),
                                 ('exact_choices', operator.eq, '必须')]:
            limit = c.get(key)
            require(limit is None or check(n, limit), f'{text}选择 {limit} 个选项')
        return sorted(value)


class TextHandler(QuestionHandler):
    validation_keys = {'min_length', 'max_length', 'format'}

    def configure(self, q):
        super().configure(q)
        c = q['validation']
        c.setdefault('format', 'plain')
        require(c['format'] in ('plain', 'digits'), '文本格式无效')
        bounds(c, 'min_length', 'max_length', True, 10000)
        require(not q['required'] or c.get('max_length') != 0, '必答文本题不能限制最多 0 字')

    def normalize(self, q, value):
        require(type(value) is str, '请输入文本')
        c = q['validation']
        if c['format'] == 'digits':
            require(re.fullmatch(r'[0-9]+', value) is not None, '只能输入 0–9，不允许空格、小数点或其他字符')
        else:
            value = value.strip()
        require(len(value) <= 10000, '文本不能超过 10000 字')
        require(c.get('min_length') is None or len(value) >= c['min_length'], '文本长度不足')
        require(c.get('max_length') is None or len(value) <= c['max_length'], '文本长度超出限制')
        return value


class NumberHandler(QuestionHandler):
    validation_keys = {'min_value', 'max_value', 'integer_only'}
    operators = {'eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'between'}

    def configure(self, q):
        super().configure(q)
        c = q['validation']
        c.setdefault('integer_only', False)
        require(type(c['integer_only']) is bool, '整数限制必须为布尔值')
        bounds(c, 'min_value', 'max_value')

    def normalize(self, q, value):
        require(finite_number(value), '请输入有效数字（绝对值不超过 10^15）')
        c = q['validation']
        require(not c['integer_only'] or value == int(value), '必须输入整数')
        require(c.get('min_value') is None or value >= c['min_value'], '数字小于最小值')
        require(c.get('max_value') is None or value <= c['max_value'], '数字大于最大值')
        return int(value) if c['integer_only'] else value


HANDLERS = {'single': SingleHandler(), 'multiple': MultipleHandler(),
            'text': TextHandler(), 'number': NumberHandler()}


def identifier(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value) is not None


def configure_questions(questions, publishing=False):
    questions = deepcopy(questions)
    require(type(questions) is list and len(questions) <= 100, '最多配置 100 道题')
    require(not publishing or bool(questions), '至少添加一道题后才能发布')
    ids = []
    for q in questions:
        require(type(q) is dict and set(q) == {'id', 'type', 'title', 'required', 'options', 'validation', 'jump_rules'},
                '题目字段不完整或包含未知字段')
        require(identifier(q['id']) and q['id'] not in ids, '题目 ID 无效或重复')
        ids.append(q['id'])
        require(type(q['type']) is str and q['type'] in HANDLERS, '不支持该题型')
        require(type(q['title']) is str and 0 < len(q['title'].strip()) <= 500, '题目标题需为 1～500 字')
        q['title'] = q['title'].strip()
        require(type(q['required']) is bool, '必答设置无效')
        require(type(q['options']) is list and len(q['options']) <= 50, '选项列表无效')
        option_ids = set()
        for o in q['options']:
            require(type(o) is dict and set(o) == {'id', 'label'}, '选项结构无效')
            require(identifier(o['id']) and o['id'] not in option_ids, '选项 ID 无效或重复')
            require(type(o['label']) is str and 0 < len(o['label'].strip()) <= 200, '选项文字需为 1～200 字')
            o['label'] = o['label'].strip()
            option_ids.add(o['id'])
        handler = HANDLERS[q['type']]
        require(type(q['validation']) is dict and set(q['validation']) <= handler.validation_keys, '校验配置包含未知字段')
        handler.configure(q)
        require(type(q['jump_rules']) is list and len(q['jump_rules']) <= 20, '每题最多 20 条跳转规则')
    for index, q in enumerate(questions):
        rule_ids = set()
        for r in q['jump_rules']:
            require(type(r) is dict and set(r) == {'id', 'operator', 'value', 'target_question_id'}, '跳转规则字段无效')
            require(identifier(r['id']) and r['id'] not in rule_ids, '规则 ID 无效或重复')
            rule_ids.add(r['id'])
            require(type(r['operator']) is str and r['operator'] in HANDLERS[q['type']].operators, '该题型不支持此跳转条件')
            require(type(r['target_question_id']) is str and r['target_question_id'] in ids[index + 1:], '跳转目标必须是后面的题目')
            value = r['value']
            opts = {o['id'] for o in q['options']}
            if q['type'] == 'single':
                require(type(value) is str and value in opts, '跳转选项不存在')
            elif q['type'] == 'multiple':
                require(type(value) is list and value and all(type(x) is str for x in value), '多选跳转需要选项列表')
                require(len(set(value)) == len(value) and set(value) <= opts, '多选跳转选项无效或重复')
            elif r['operator'] == 'between':
                require(type(value) is dict and set(value) == {'min', 'max'}, '区间必须包含 min 和 max')
                require(finite_number(value['min']) and finite_number(value['max']) and value['min'] <= value['max'], '跳转区间无效')
            else:
                require(finite_number(value), '数字跳转条件必须为有效数字')
    return questions


def empty(q, value):
    if value is None or value == '' or value == []:
        return True
    return (q['type'] == 'text' and q['validation'].get('format', 'plain') == 'plain'
            and type(value) is str and not value.strip())


def normalize_answer(q, value):
    if empty(q, value):
        require(not q['required'], '此题必须回答', field=q['id'])
        return None
    try:
        return HANDLERS[q['type']].normalize(q, value)
    except BusinessError as e:
        e.field = q['id']
        raise


def next_question(questions, index, value):
    q = questions[index]
    if value is not None:
        for rule in q['jump_rules']:
            if OPERATORS[rule['operator']](value, rule['value']):
                return next(i for i, target in enumerate(questions) if target['id'] == rule['target_question_id'])
    return index + 1


def evaluate(questions, answers, partial=False):
    """返回规范答案与有效路径。partial 模式停在首个尚未回答的题，供前端逐题导航。"""
    values = {}
    for answer in answers:
        qid = answer['question_id']
        require(qid not in values, '同一题不能提交多个答案')
        values[qid] = answer['value']
    require(set(values) <= {q['id'] for q in questions}, '包含不存在的题目')
    index, path, normalized = 0, [], []
    while index < len(questions):
        q = questions[index]
        path.append(q['id'])
        if partial and q['id'] not in values:
            return {'path': path, 'answers': normalized, 'next_question_id': q['id'], 'complete': False}
        value = normalize_answer(q, values.get(q['id']))
        if value is not None:
            normalized.append({'question_id': q['id'], 'value': value})
        index = next_question(questions, index, value)
    return {'path': path, 'answers': normalized, 'next_question_id': None, 'complete': True}
