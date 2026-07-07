"""Pydantic models for request validation."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


VALID_TASK_STATUSES = ("todo", "doing", "in_review", "done", "blocked")


class ProjectCreate(BaseModel):
    name_en: str = Field(min_length=1, max_length=200)
    name_zh: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)
    color: str = Field(default="#00ddb3", max_length=30)


class ProjectUpdate(BaseModel):
    name_en: Optional[str] = Field(default=None, min_length=1, max_length=200)
    name_zh: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    color: Optional[str] = Field(default=None, max_length=30)


class WorkstreamCreate(BaseModel):
    project_id: str = Field(min_length=1)
    title_en: str = Field(min_length=1, max_length=500)
    title_zh: str = Field(default="", max_length=500)
    owner: str = Field(default="", max_length=100)
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    status: Literal["planned", "in-progress", "blocked", "review", "done", "stable"] = "planned"
    summary_en: str = Field(default="", max_length=5000)
    summary_zh: str = Field(default="", max_length=5000)


class WorkstreamUpdate(BaseModel):
    title_en: Optional[str] = Field(default=None, min_length=1, max_length=500)
    title_zh: Optional[str] = Field(default=None, max_length=500)
    owner: Optional[str] = Field(default=None, max_length=100)
    priority: Optional[Literal["critical", "high", "medium", "low"]] = None
    status: Optional[Literal["planned", "in-progress", "blocked", "review", "done", "stable"]] = None
    summary_en: Optional[str] = Field(default=None, max_length=5000)
    summary_zh: Optional[str] = Field(default=None, max_length=5000)


class TaskCreate(BaseModel):
    workstream_id: str = Field(min_length=1)
    parent_task_id: Optional[str] = None
    title_en: str = Field(min_length=1, max_length=500)
    title_zh: str = Field(default="", max_length=500)
    assignee: str = Field(default="", max_length=100)
    status: Literal["todo", "doing", "in_review", "done", "blocked", "abandoned"] = "todo"
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    start_date: Optional[str] = Field(default=None, max_length=20)
    due_date: Optional[str] = Field(default=None, max_length=20)
    notes: str = Field(default="", max_length=5000)


class TaskUpdate(BaseModel):
    title_en: Optional[str] = Field(default=None, min_length=1, max_length=500)
    title_zh: Optional[str] = Field(default=None, max_length=500)
    parent_task_id: Optional[str] = None
    assignee: Optional[str] = Field(default=None, max_length=100)
    status: Optional[Literal["todo", "doing", "in_review", "done", "blocked", "abandoned"]] = None
    priority: Optional[Literal["critical", "high", "medium", "low"]] = None
    start_date: Optional[str] = Field(default=None, max_length=20)
    due_date: Optional[str] = Field(default=None, max_length=20)
    notes: Optional[str] = Field(default=None, max_length=5000)


class BlockerCreate(BaseModel):
    workstream_id: str = Field(min_length=1)
    description_en: str = Field(min_length=1, max_length=2000)
    description_zh: str = Field(default="", max_length=2000)
    assignee: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=5000)


class BlockerUpdate(BaseModel):
    description_en: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    description_zh: Optional[str] = Field(default=None, max_length=2000)
    assignee: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=5000)


class BugCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    status: Literal["open", "investigating", "fixing", "fix_complete", "to_verify", "resolved", "closed", "wontfix"] = "open"
    reporter: str = Field(default="", max_length=100)
    assignee: str = Field(default="", max_length=100)
    project_id: Optional[str] = None
    workstream_id: Optional[str] = None
    task_id: Optional[str] = None
    environment: str = Field(default="", max_length=500)
    steps_to_reproduce: str = Field(default="", max_length=5000)
    issue_time: Optional[str] = Field(default=None, max_length=30)
    feature: str = Field(default="", max_length=200)
    repro_rate: str = Field(default="", max_length=50)
    issue_version: str = Field(default="", max_length=100)
    device_id: str = Field(default="", max_length=50)
    # List of attachment dicts ({file_token, name, size, type}); stored JSON-encoded.
    issue_images: Optional[List[Dict[str, Any]]] = None
    source: Literal["manual", "agent"] = "manual"
    fix_method: str = Field(default="", max_length=5000)
    fix_version: str = Field(default="", max_length=200)
    fix_date: str = Field(default="", max_length=30)


class BugUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)
    severity: Optional[Literal["critical", "high", "medium", "low"]] = None
    status: Optional[Literal["open", "investigating", "fixing", "fix_complete", "to_verify", "resolved", "closed", "wontfix"]] = None
    assignee: Optional[str] = Field(default=None, max_length=100)
    project_id: Optional[str] = None
    workstream_id: Optional[str] = None
    task_id: Optional[str] = None
    environment: Optional[str] = Field(default=None, max_length=500)
    steps_to_reproduce: Optional[str] = Field(default=None, max_length=5000)
    issue_time: Optional[str] = Field(default=None, max_length=30)
    feature: Optional[str] = Field(default=None, max_length=200)
    repro_rate: Optional[str] = Field(default=None, max_length=50)
    issue_version: Optional[str] = Field(default=None, max_length=100)
    device_id: Optional[str] = Field(default=None, max_length=50)
    issue_images: Optional[List[Dict[str, Any]]] = None
    fix_method: Optional[str] = Field(default=None, max_length=5000)
    fix_version: Optional[str] = Field(default=None, max_length=200)
    fix_date: Optional[str] = Field(default=None, max_length=30)


class ImportPayload(BaseModel):
    """Import from session-status.json format."""
    project_id: str = Field(min_length=1)
    data: Dict[str, Any]


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(default="", max_length=200)
    role: Literal["human", "bot"] = "human"


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=200)
    role: Optional[Literal["human", "bot"]] = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ReorderItem(BaseModel):
    id: str = Field(min_length=1)
    sort_order: int = Field(ge=0)


class ReorderRequest(BaseModel):
    items: List[ReorderItem] = Field(min_length=1)


class BulkTaskAction(BaseModel):
    task_ids: List[str] = Field(min_length=1)
    action: Literal["update", "delete"]
    fields: Optional[Dict[str, Any]] = None


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    project_id: Optional[str] = None
    structure: List[Dict[str, Any]] = Field(min_length=1)


class TemplateApply(BaseModel):
    workstream_id: str = Field(min_length=1)


class DependencyCreate(BaseModel):
    depends_on_id: str = Field(min_length=1)
    dep_type: Literal["blocked_by", "related"] = "blocked_by"


class TimeEntryCreate(BaseModel):
    minutes: int = Field(ge=1, le=1440)
    description: str = Field(default="", max_length=1000)
    date: Optional[str] = Field(default=None, max_length=20)


class RecurringTaskCreate(BaseModel):
    workstream_id: str = Field(min_length=1)
    title_en: str = Field(min_length=1, max_length=500)
    title_zh: str = Field(default="", max_length=500)
    assignee: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=5000)
    schedule: Literal["daily", "weekly", "biweekly", "monthly"] = "weekly"
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)


class RecurringTaskUpdate(BaseModel):
    title_en: Optional[str] = Field(default=None, min_length=1, max_length=500)
    title_zh: Optional[str] = Field(default=None, max_length=500)
    assignee: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=5000)
    schedule: Optional[Literal["daily", "weekly", "biweekly", "monthly"]] = None
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    active: Optional[int] = Field(default=None, ge=0, le=1)


class ConflictResolve(BaseModel):
    resolution: Literal["local", "remote", "manual"]
    manual_value: Optional[str] = Field(default=None, max_length=5000)


class NotificationPrefUpdate(BaseModel):
    overdue: Optional[int] = Field(default=None, ge=0, le=1)
    stale: Optional[int] = Field(default=None, ge=0, le=1)
    blocker: Optional[int] = Field(default=None, ge=0, le=1)
    digest: Optional[int] = Field(default=None, ge=0, le=1)
    stale_days: Optional[int] = Field(default=None, ge=1, le=90)
