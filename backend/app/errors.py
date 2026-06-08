from fastapi import HTTPException


class ApiError(HTTPException):
    """HTTPException whose detail is pre-shaped for the {"error": {code, message}} envelope."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
