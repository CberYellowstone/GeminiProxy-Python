from typing import Optional, Union


class ApiException(Exception):
    def __init__(self, status_code: int, detail: Union[dict, str, None]):
        self.status_code = status_code
        self.detail = detail
        self.sha256_to_reset: Optional[str] = None  # 用于携带需要重置的文件的sha256
