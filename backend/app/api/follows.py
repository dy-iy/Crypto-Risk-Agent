from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.api.auth import SESSION_COOKIE_NAME
from app.services.auth_service import get_user_by_session
from app.services.follow_service import follow_snapshot, mutate_follow

router = APIRouter(prefix='/api/follows', tags=['follows'])


class FollowItem(BaseModel):
    symbol: str
    base_asset: str
    name: str
    alert_threshold: int = Field(ge=0, le=100)
    created_at: str
    updated_at: str


class FollowSnapshot(BaseModel):
    items: list[FollowItem]
    revision: str


class FollowCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    symbol: str = Field(min_length=1, max_length=24)


class FollowThreshold(BaseModel):
    model_config = ConfigDict(extra='forbid')
    alert_threshold: int = Field(ge=0, le=100, strict=True)


def _user(session: str | None) -> str:
    user = get_user_by_session(session)
    if not user:
        raise HTTPException(401, '请先登录后同步关注币种')
    return user.id


def _change(user_id, symbol, action, threshold=None):
    try:
        return mutate_follow(user_id, symbol, action, threshold)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('', response_model=FollowSnapshot)
def follows(cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    return follow_snapshot(_user(cryptorisk_session))


@router.post('', response_model=FollowSnapshot)
def add_follow(payload: FollowCreate, cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    return _change(_user(cryptorisk_session), payload.symbol, 'add')


@router.patch('/{symbol}', response_model=FollowSnapshot)
def update_follow(symbol: str, payload: FollowThreshold, cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    return _change(_user(cryptorisk_session), symbol, 'threshold', payload.alert_threshold)


@router.delete('/{symbol}', response_model=FollowSnapshot)
def remove_follow(symbol: str, cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    return _change(_user(cryptorisk_session), symbol, 'remove')
