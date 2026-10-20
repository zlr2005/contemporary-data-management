from typing import Any
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


class MetadataInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=5000)
    deadline_at: str | None = None


class Answer(Input):
    question_id: str = Field(min_length=1, max_length=80)
    value: Any


class AnswerRequest(Input):
    answers: list[Answer] = Field(default_factory=list, max_length=100)


class SubmitRequest(AnswerRequest):
    submission_key: str = Field(min_length=1, max_length=80)
