from __future__ import annotations

from datetime import datetime
import random
from typing import Dict

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from app.db import (
    Team,
    TeamMember,
    User,
    PRStatus,
    PullRequest,
    PullRequestShort,
    SetIsActiveRequest,
    CreatePullRequestRequest,
    MergePullRequestRequest,
    ReassignReviewerRequest,
    TeamResponse,
    UserResponse,
    PullRequestResponse,
    ReassignReviewerResponse,
    UserReviewsResponse,
    ErrorCode,
)

app = FastAPI(title="PR Reviewer Assignment Service")

# ===== In-memory "DB" =====

users_by_id: Dict[str, User] = {}
prs_by_id: Dict[str, PullRequest] = {}
teams_exist: set[str] = set()  # имена команд, которые создавали через /team/add


# ===== Helpers =====

def error_response(status: int, code: ErrorCode, msg: str):
    # возвращаем ErrorResponse в формате OpenAPI
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code.value,
                "message": msg,
            }
        },
    )


# ===== Health =====

@app.get("/health")
def health():
    return {"status": "Сервис жив :)"}


# ===== Teams =====

@app.post("/team/add", response_model=TeamResponse, status_code=201)
def add_team(team: Team):
    # команда уже существует?
    if team.team_name in teams_exist:
        return error_response(400, ErrorCode.TEAM_EXISTS, "team_name already exists")

    # помечаем команду как существующую
    teams_exist.add(team.team_name)

    # создаём/обновляем пользователей
    for member in team.members:
        u_id = member.user_id
        if u_id in users_by_id:
            # обновление существующего пользователя
            existing = users_by_id[u_id]
            existing.username = member.username
            existing.team_name = team.team_name
            existing.is_active = member.is_active
        else:
            # новый пользователь
            users_by_id[u_id] = User(
                user_id=member.user_id,
                username=member.username,
                team_name=team.team_name,
                is_active=member.is_active,
            )

    return TeamResponse(team=team)


@app.get("/team/get", response_model=Team)
def get_team(team_name: str = Query(..., description="Уникальное имя команды")):
    if team_name not in teams_exist:
        return error_response(404, ErrorCode.NOT_FOUND, "team not found")

    members: list[TeamMember] = []
    for user in users_by_id.values():
        if user.team_name == team_name:
            members.append(
                TeamMember(
                    user_id=user.user_id,
                    username=user.username,
                    is_active=user.is_active,
                )
            )

    return Team(team_name=team_name, members=members)


# ===== Users =====

@app.post("/users/setIsActive", response_model=UserResponse)
def set_is_active(payload: SetIsActiveRequest):
    user_id = payload.user_id
    if user_id not in users_by_id:
        return error_response(404, ErrorCode.NOT_FOUND, "user not found")

    user = users_by_id[user_id]
    user.is_active = payload.is_active
    users_by_id[user_id] = user
    return UserResponse(user=user)


# ===== Pull Requests =====

@app.post("/pullRequest/create", response_model=PullRequestResponse, status_code=201)
def create_pull_request(payload: CreatePullRequestRequest):
    pr_id = payload.pull_request_id

    # PR уже существует?
    if pr_id in prs_by_id:
        return error_response(409, ErrorCode.PR_EXISTS, "PR id already exists")

    # автор существует?
    author = users_by_id.get(payload.author_id)
    if author is None:
        return error_response(404, ErrorCode.NOT_FOUND, "author not found")

    # команда автора существует?
    if author.team_name not in teams_exist:
        return error_response(404, ErrorCode.NOT_FOUND, "author team not found")

    # выбираем ревьюеров
    candidates: list[str] = []
    for u in users_by_id.values():
        if (
            u.team_name == author.team_name
            and u.user_id != author.user_id
            and u.is_active
        ):
            candidates.append(u.user_id)

    random.shuffle(candidates)
    assigned_reviewers = candidates[:2]

    pr = PullRequest(
        pull_request_id=pr_id,
        pull_request_name=payload.pull_request_name,
        author_id=author.user_id,
        status=PRStatus.OPEN,
        assigned_reviewers=assigned_reviewers,
        createdAt=datetime.utcnow(),
        mergedAt=None,
    )

    prs_by_id[pr_id] = pr
    return PullRequestResponse(pr=pr)


@app.post("/pullRequest/merge", response_model=PullRequestResponse)
def merge_pull_request(payload: MergePullRequestRequest):
    pr_id = payload.pull_request_id
    pr = prs_by_id.get(pr_id)

    if pr is None:
        return error_response(404, ErrorCode.NOT_FOUND, "PR not found")

    if pr.status == PRStatus.MERGED:
        # идемпотентность — просто вернуть текущее состояние
        return PullRequestResponse(pr=pr)

    pr.status = PRStatus.MERGED
    pr.mergedAt = datetime.utcnow()
    prs_by_id[pr_id] = pr
    return PullRequestResponse(pr=pr)


@app.post("/pullRequest/reassign", response_model=ReassignReviewerResponse)
def reassign_reviewer(payload: ReassignReviewerRequest):
    pr_id = payload.pull_request_id
    old_user_id = payload.old_user_id

    pr = prs_by_id.get(pr_id)
    if pr is None:
        return error_response(404, ErrorCode.NOT_FOUND, "PR not found")

    old_user = users_by_id.get(old_user_id)
    if old_user is None:
        return error_response(404, ErrorCode.NOT_FOUND, "user not found")

    # нельзя менять после MERGED
    if pr.status == PRStatus.MERGED:
        return error_response(409, ErrorCode.PR_MERGED, "cannot reassign on merged PR")

    # пользователь не назначен ревьювером
    if old_user_id not in pr.assigned_reviewers:
        return error_response(
            409, ErrorCode.NOT_ASSIGNED, "reviewer is not assigned to this PR"
        )

    # ищем кандидатов из команды old_user
    candidates: list[str] = []
    for u in users_by_id.values():
        if (
            u.team_name == old_user.team_name
            and u.user_id != old_user_id
            and u.is_active
            and u.user_id not in pr.assigned_reviewers
        ):
            candidates.append(u.user_id)

    if not candidates:
        return error_response(
            409,
            ErrorCode.NO_CANDIDATE,
            "no active replacement candidate in team",
        )

    new_user_id = random.choice(candidates)

    # заменяем в списке ревьюеров
    new_reviewers = [
        (new_user_id if r == old_user_id else r) for r in pr.assigned_reviewers
    ]
    pr.assigned_reviewers = new_reviewers
    prs_by_id[pr_id] = pr

    return ReassignReviewerResponse(pr=pr, replaced_by=new_user_id)


# ===== Users review list =====

@app.get("/users/getReview", response_model=UserReviewsResponse)
def get_user_reviews(user_id: str = Query(..., description="Идентификатор пользователя")):
    # если хочешь строго по ТЗ — можно 404, если юзер не существует:
    if user_id not in users_by_id:
        return error_response(404, ErrorCode.NOT_FOUND, "user not found")

    pull_requests_short: list[PullRequestShort] = []

    for pr in prs_by_id.values():
        if user_id in pr.assigned_reviewers:
            pull_requests_short.append(
                PullRequestShort(
                    pull_request_id=pr.pull_request_id,
                    pull_request_name=pr.pull_request_name,
                    author_id=pr.author_id,
                    status=pr.status,
                )
            )

    return UserReviewsResponse(user_id=user_id, pull_requests=pull_requests_short)
