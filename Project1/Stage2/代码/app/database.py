"""MongoDB 连接、结构校验及索引。业务数据不写入本地文件。"""
from pymongo import MongoClient


def obj(properties, required):
    return {'bsonType': 'object', 'required': required, 'properties': properties}


def initialize(db):
    string = {'bsonType': 'string'}
    oid = {'bsonType': 'objectId'}
    date = {'bsonType': 'date'}
    boolean = {'bsonType': 'bool'}
    rule = obj({'id': string, 'operator': string, 'value': {}, 'target_question_id': string},
               ['id', 'operator', 'value', 'target_question_id'])
    question = obj({
        'id': string, 'type': {'enum': ['single', 'multiple', 'text', 'number']},
        'title': string, 'required': boolean,
        'options': {'bsonType': 'array', 'items': obj({'id': string, 'label': string}, ['id', 'label'])},
        'validation': {'bsonType': 'object'},
        'jump_rules': {'bsonType': 'array', 'items': rule},
    }, ['id', 'type', 'title', 'required', 'options', 'validation', 'jump_rules'])
    common = {'_id': oid, 'schema_version': {'bsonType': 'int', 'enum': [1]}}
    schemas = {
        'users': obj({**common, 'username': string, 'username_key': string,
                      'password_hash': string, 'created_at': date},
                     ['username', 'username_key', 'password_hash', 'created_at', 'schema_version']),
        'surveys': obj({**common, 'owner_id': oid, 'title': string, 'description': string,
                       'share_code': string, 'status': {'enum': ['draft', 'published', 'closed']},
                       'allow_anonymous': boolean, 'allow_repeat': boolean,
                       'deadline_at': {'bsonType': ['date', 'null']},
                       'questions': {'bsonType': 'array', 'items': question},
                       'published_at': {'bsonType': ['date', 'null']},
                       'closed_at': {'bsonType': ['date', 'null']},
                       'created_at': date, 'updated_at': date},
                      ['owner_id', 'title', 'description', 'share_code', 'status', 'allow_anonymous',
                       'allow_repeat', 'deadline_at', 'questions', 'published_at', 'closed_at',
                       'created_at', 'updated_at', 'schema_version']),
        'responses': obj({**common, 'survey_id': oid, 'respondent_id': oid,
                         'repeat_allowed': boolean, 'submission_key': string,
                         'path': {'bsonType': 'array', 'items': string},
                         'answers': {'bsonType': 'array', 'items': obj({
                             'question_id': string,
                             'value': {'bsonType': ['string', 'array', 'int', 'long', 'double']}},
                             ['question_id', 'value'])}, 'submitted_at': date},
                        ['survey_id', 'respondent_id', 'repeat_allowed', 'submission_key',
                         'path', 'answers', 'submitted_at', 'schema_version']),
    }
    bound_question = obj({**question['properties'], 'series_id': oid, 'version_id': oid},
                         question['required'] + ['series_id', 'version_id'])
    schemas['surveys']['properties']['schema_version'] = {'bsonType': 'int', 'enum': [1, 2]}
    schemas['surveys']['anyOf'] = [
        {'properties': {'schema_version': {'enum': [1]}}},
        {'properties': {'schema_version': {'enum': [2]},
                        'questions': {'bsonType': 'array', 'items': bound_question}}},
    ]
    nullable_oid = {'bsonType': ['objectId', 'null']}
    content = obj({key: question['properties'][key]
                   for key in ('type', 'title', 'required', 'options', 'validation')},
                  ['type', 'title', 'required', 'options', 'validation'])
    schemas['question_series'] = obj({
        **common, 'owner_id': oid, 'name': string, 'status': {'enum': ['active', 'archived']},
        'version_counter': {'bsonType': 'int', 'minimum': 0}, 'creation_hash': string,
        'forked_from_series_id': nullable_oid, 'forked_from_version_id': nullable_oid,
        'legacy_key': string, 'created_at': date, 'updated_at': date,
    }, ['owner_id', 'name', 'status', 'version_counter', 'creation_hash', 'created_at',
        'updated_at', 'schema_version', 'forked_from_series_id', 'forked_from_version_id'])
    schemas['question_versions'] = obj({
        **common, 'series_id': oid, 'version_no': {'bsonType': 'int', 'minimum': 1},
        'content': content, 'parent_version_id': nullable_oid, 'restored_from_version_id': nullable_oid,
        'operation': {'enum': ['create', 'edit', 'restore', 'fork', 'migrate']},
        'created_by': oid, 'created_at': date, 'request_key': string, 'request_hash': string,
    }, ['series_id', 'version_no', 'content', 'parent_version_id', 'restored_from_version_id',
        'operation', 'created_by', 'created_at', 'request_key', 'request_hash', 'schema_version'])
    grant_common = {**common, 'grantee_id': oid, 'granted_by': oid,
                    'status': {'enum': ['active', 'revoked']}, 'created_at': date, 'updated_at': date,
                    'revoked_at': {'bsonType': ['date', 'null']}}
    grant_required = ['grantee_id', 'granted_by', 'status', 'created_at', 'updated_at', 'revoked_at', 'schema_version']
    schemas['question_shares'] = obj({**grant_common, 'series_id': oid}, grant_required + ['series_id'])
    schemas['statistic_grants'] = obj({**grant_common, 'survey_id': oid, 'question_id': string,
                                       'version_id': oid, 'allow_contents': boolean},
                                      grant_required + ['survey_id', 'question_id', 'version_id', 'allow_contents'])
    bank_item = obj({'series_id': oid, 'version_id': oid, 'content': content, 'added_at': date},
                    ['series_id', 'version_id', 'content', 'added_at'])
    schemas['question_banks'] = obj({**common, 'owner_id': oid, 'name': string, 'description': string,
        'items': {'bsonType': 'array', 'maxItems': 500, 'items': bank_item},
        'revision': {'bsonType': 'int', 'minimum': 1}, 'created_at': date, 'updated_at': date},
        ['owner_id', 'name', 'description', 'items', 'revision', 'created_at', 'updated_at', 'schema_version'])
    for name, schema in schemas.items():
        opts = dict(validator={'$jsonSchema': schema}, validationLevel='strict', validationAction='error')
        if name in db.list_collection_names():
            db.command({'collMod': name, **opts})
        else:
            db.create_collection(name, **opts)
    db.users.create_index('username_key', unique=True, name='uq_username_key')
    db.surveys.create_index('share_code', unique=True, name='uq_share_code')
    db.surveys.create_index([('owner_id', 1), ('created_at', -1)], name='ix_owner_created')
    db.responses.create_index([('survey_id', 1), ('submitted_at', -1)], name='ix_survey_submitted')
    db.responses.create_index([('survey_id', 1), ('respondent_id', 1)], unique=True,
                              partialFilterExpression={'repeat_allowed': False}, name='uq_one_response_per_user')
    db.responses.create_index([('survey_id', 1), ('respondent_id', 1), ('submission_key', 1)],
                              unique=True, name='uq_submission_retry')
    db.question_series.create_index([('owner_id', 1), ('created_at', -1)], name='ix_question_owner')
    db.question_series.create_index('legacy_key', unique=True,
                                   partialFilterExpression={'legacy_key': {'$type': 'string'}}, name='uq_legacy_question')
    db.question_versions.create_index([('series_id', 1), ('version_no', 1)], unique=True, name='uq_series_version')
    db.question_versions.create_index([('created_by', 1), ('request_key', 1)], unique=True, name='uq_version_request')
    db.surveys.create_index('questions.version_id', name='ix_question_version')
    db.surveys.create_index('questions.series_id', name='ix_question_series')
    db.question_shares.create_index([('series_id', 1), ('grantee_id', 1)], unique=True, name='uq_series_grantee')
    db.question_shares.create_index([('grantee_id', 1), ('status', 1)], name='ix_received_shares')
    db.question_banks.create_index([('owner_id', 1), ('updated_at', -1)], name='ix_bank_owner')
    db.statistic_grants.create_index([('survey_id', 1), ('question_id', 1), ('grantee_id', 1)], unique=True, name='uq_statistics_grantee')
    db.statistic_grants.create_index([('grantee_id', 1), ('status', 1), ('version_id', 1)], name='ix_received_statistics')


def connect(settings):
    client = MongoClient(settings.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=4000)
    client.admin.command('ping')
    db = client[settings.database]
    initialize(db)
    return client, db
