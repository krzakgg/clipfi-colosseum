from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    account_type: Literal["company", "creator"]
    login: str = Field(min_length=1)
    password: str = Field(min_length=8)