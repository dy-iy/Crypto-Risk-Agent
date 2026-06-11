from pydantic import BaseModel, Field


class AuthUser(BaseModel):
    id: str
    username: str
    display_name: str
    created_at: str
    is_admin: bool = False


class AuthSessionItem(BaseModel):
    session_id: str
    created_at: str
    expires_at: str
    client_ip_hash: str = ""
    user_agent: str = ""
    is_current: bool = False


class AuthCredentials(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=10, max_length=128)


class AuthResponse(BaseModel):
    status: str = "success"
    message: str
    user: AuthUser
