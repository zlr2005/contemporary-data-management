from datetime import datetime, timezone, timedelta
from bson import ObjectId
import jwt
from pwdlib import PasswordHash
from .errors import BusinessError

hasher = PasswordHash.recommended()
DUMMY_HASH = hasher.hash('not-a-real-password-for-timing')


def issue_token(user_id, secret, hours):
    now = datetime.now(timezone.utc)
    return jwt.encode({'sub': str(user_id), 'iat': now, 'exp': now + timedelta(hours=hours)},
                      secret, algorithm='HS256')


def read_token(token, secret):
    try:
        data = jwt.decode(token, secret, algorithms=['HS256'], options={'require': ['exp', 'sub', 'iat']})
        return ObjectId(data['sub'])
    except (jwt.PyJWTError, ValueError, TypeError):
        raise BusinessError('登录已过期，请重新登录', 401)
