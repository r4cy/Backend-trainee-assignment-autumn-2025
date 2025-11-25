from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


# =========================
# Ошибки
# =========================

class ErrorCode(str, Enum):
    TEAM_EXISTS = "TEAM_EXISTS"
    PR_EXISTS = "PR_EXISTS"
    PR_MERGED = "PR_MERGED"
    NOT_ASSIGNED = "NOT_ASSIGNED"
    NO_CANDIDATE = "NO_CANDIDATE"
    NOT_FOUND = "NOT_FOUND"


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


# =========================
# Базовые сущности
# =========================

class TeamMember(BaseModel):
    user_id: str
    username: str
    is_active: bool


class Team(BaseModel):
    team_name: str
    members: List[TeamMember]


class User(BaseModel):
    user_id: str
    username: str
    team_name: str
    is_active: bool


class PRStatus(str, Enum):
    OPEN = "OPEN"
    MERGED = "MERGED"


class PullRequest(BaseModel):
    pull_request_id: str
    pull_request_name: str
    author_id: str
    status: PRStatus
    assigned_reviewers: List[str]  # user_id ревьюверов (0..2)
    createdAt: Optional[datetime] = None
    mergedAt: Optional[datetime] = None


class PullRequestShort(BaseModel):
    pull_request_id: str
    pull_request_name: str
    author_id: str
    status: PRStatus


# =========================
# Тела запросов
# =========================

class SetIsActiveRequest(BaseModel):
    user_id: str
    is_active: bool


class CreatePullRequestRequest(BaseModel):
    pull_request_id: str
    pull_request_name: str
    author_id: str


class MergePullRequestRequest(BaseModel):
    pull_request_id: str


class ReassignReviewerRequest(BaseModel):
    pull_request_id: str
    old_user_id: str   # в OpenAPI так называется поле


# =========================
# Обёртки ответов (response models)
# =========================

class TeamResponse(BaseModel):
    team: Team


class UserResponse(BaseModel):
    user: User


class PullRequestResponse(BaseModel):
    pr: PullRequest


class ReassignReviewerResponse(BaseModel):
    pr: PullRequest
    replaced_by: str  # user_id нового ревьювера


class UserReviewsResponse(BaseModel):
    user_id: str
    pull_requests: List[PullRequestShort]
