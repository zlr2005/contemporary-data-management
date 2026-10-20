class BusinessError(Exception):
    def __init__(self, message, status=422, field=None):
        self.message, self.status, self.field = message, status, field


def require(condition, message, status=422, field=None):
    if not condition:
        raise BusinessError(message, status, field)
