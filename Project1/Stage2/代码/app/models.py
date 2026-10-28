from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Credentials(Input):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class SurveyInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=5000)
    allow_anonymous: bool = False
    allow_repeat: bool = False
    deadline_at: str | None = None
    questions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    expected_updated_at: str | None = None


class MetadataInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=5000)
    deadline_at: str | None = None
    expected_updated_at: str | None = None


class Answer(Input):
    question_id: str = Field(min_length=1, max_length=80)
    value: Any


class AnswerRequest(Input):
    answers: list[Answer] = Field(default_factory=list, max_length=100)


class SubmitRequest(AnswerRequest):
    submission_key: str = Field(min_length=1, max_length=80)


class QuestionCreate(Input):
    name: str = Field(min_length=1, max_length=200)
    content: dict[str, Any]
    request_key: str = Field(min_length=1, max_length=80)


class VersionCreate(Input):
    parent_version_id: str
    content: dict[str, Any]
    request_key: str = Field(min_length=1, max_length=80)


class VersionRestore(Input):
    base_version_id: str
    restore_version_id: str
    request_key: str = Field(min_length=1, max_length=80)


class QuestionPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal['active', 'archived'] | None = None


class ShareInput(Input):
    username: str = Field(min_length=1, max_length=50)


class StatisticGrantInput(ShareInput):
    allow_contents: bool = False


class BankCreate(Input):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=5000)


class BankSave(BankCreate):
    version_ids: list[str] = Field(max_length=500)
    revision: int = Field(ge=1)


class BankDelete(Input):
    revision: int = Field(ge=1)
