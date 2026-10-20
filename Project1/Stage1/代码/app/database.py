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


def connect(settings):
    client = MongoClient(settings.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=4000)
    client.admin.command('ping')
    db = client[settings.database]
    initialize(db)
    return client, db
