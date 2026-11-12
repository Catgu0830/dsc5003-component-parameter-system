from flask import jsonify, request


class APIError(Exception):
    def __init__(self, message, status=400, data=None):
        self.message, self.status, self.data = message, status, data


def ok(data=None, status=200, message='success'):
    return jsonify(code=0, message=message, data=data if data is not None else {}), status


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise APIError('Request body must be a JSON object')
    return value


def text(value, name, max_length=200, required=True):
    if value is None:
        if required:
            raise APIError(f'{name} must be a non-empty string of at most {max_length} characters')
        return None
    if not isinstance(value, str) or len(value) > max_length or (required and not value.strip()):
        raise APIError(f'{name} must be a non-empty string of at most {max_length} characters')
    return value.strip() or None


def integer(value, name, low=1, high=1000000000):
    try:
        if isinstance(value, bool) or str(value) != str(int(value)):
            raise ValueError()
        n = int(value)
    except (ValueError, TypeError, OverflowError):
        raise APIError(f'{name} must be an integer')
    if not low <= n <= high:
        raise APIError(f'{name} must be between {low} and {high}')
    return n


def pagination(query=None):
    query=request.args if query is None else query
    return integer(query.get('page', '1'), 'page'), integer(query.get('page_size', '20'), 'page_size', 1, 100)


def confirmed(data):
    if data.get('confirm') is not True:
        raise APIError('Explicit confirmation required: confirm=true')
