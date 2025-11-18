class ApiException(Exception):

    def __init__(self, status_code: int, detail: dict | str | None):
        self.status_code = status_code
        self.detail = detail
        self.is_resettable = False  # 用于标记是否是可触发全局重置的文件错误
