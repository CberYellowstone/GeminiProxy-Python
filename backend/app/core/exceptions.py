class ApiException(Exception):

    def __init__(self, status_code: int, detail: dict | str | None):
        self.status_code = status_code
        self.detail = detail
