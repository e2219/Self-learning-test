from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr, model_validator

QuestionType = Literal["choice", "true_false", "fill", "calculation", "proof"]


class LoginInput(BaseModel):
    code: str = Field(min_length=1, max_length=200)


class CourseInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class SettingsInput(BaseModel):
    api_key: str = Field(default="", max_length=500)
    clear_key: bool = False
    model: Literal["deepseek-chat", "deepseek-reasoner"] = "deepseek-chat"


class PageInput(BaseModel):
    text: str = Field(max_length=50_000)


class SourceRange(BaseModel):
    document_id: str
    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("结束页不能小于开始页")
        return self


class TypeRule(BaseModel):
    type: QuestionType
    count: int = Field(ge=0, le=30)
    points: float = Field(gt=0, le=100, allow_inf_nan=False)


class PlanSlot(BaseModel):
    topic_id: str = Field(min_length=1, max_length=64)
    type: QuestionType
    points: float = Field(gt=0, le=100, allow_inf_nan=False)
    objective: str = Field(min_length=1, max_length=500)


class ExamInput(BaseModel):
    course_id: str
    title: str = Field(min_length=1, max_length=100)
    ranges: list[SourceRange] = Field(min_length=1, max_length=10)
    rules: list[TypeRule] = Field(min_length=1, max_length=5)
    mode: Literal["custom", "random"] = "custom"
    random_count: int = Field(default=10, ge=1, le=30)
    difficulty: Literal["基础巩固", "综合应用", "挑战题"] = "基础巩固"
    focus: str = Field(default="", max_length=500)
    duration: int = Field(default=60, ge=5, le=240)
    plan_id: str | None = Field(default=None, max_length=64)
    blueprint: list[PlanSlot] = Field(default_factory=list, max_length=30)
    style: Literal["贴近原题", "适度变式", "情景应用"] = "适度变式"

    @model_validator(mode="after")
    def valid_counts(self):
        if len({r.type for r in self.rules}) != len(self.rules):
            raise ValueError("题型不能重复")
        if self.mode == "custom" and not 1 <= sum(r.count for r in self.rules) <= 30:
            raise ValueError("每份试卷需要 1 至 30 道题")
        return self


class Citation(BaseModel):
    document_id: str
    page: int = Field(ge=1)


class BlankAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=1000)
    alternatives: list[str] = Field(default_factory=list, max_length=10)


class GeneratedQuestion(BaseModel):
    _review: dict = PrivateAttr(default_factory=dict)
    blanks: list[BlankAnswer] = Field(default_factory=list, max_length=12)
    stem: str = Field(min_length=5, max_length=12000)
    options: list[str] = Field(default_factory=list, max_length=6)
    answer: str = Field(min_length=1, max_length=12000)
    explanation: str = Field(min_length=1, max_length=20000)
    rubric: list[str] = Field(min_length=1, max_length=12)
    knowledge: str = Field(min_length=1, max_length=300)
    sources: list[Citation] = Field(min_length=1, max_length=12)


class QuestionEdit(GeneratedQuestion):
    points: float = Field(gt=0, le=100, allow_inf_nan=False)


class ProgressInput(BaseModel):
    user_answer: str | None = Field(default=None, max_length=20000)
    self_score: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    is_wrong: bool | None = None
    is_favorite: bool | None = None


class OCRInput(BaseModel):
    start: int = Field(ge=1)
    end: int = Field(ge=1)
    force: bool = False


class TableReviewInput(BaseModel):
    text_hash: str = Field(min_length=64, max_length=64)
    confirmed: bool = False


class RegionInput(BaseModel):
    x: float = Field(ge=0, lt=1, allow_inf_nan=False)
    y: float = Field(ge=0, lt=1, allow_inf_nan=False)
    width: float = Field(ge=0.05, le=1, allow_inf_nan=False)
    height: float = Field(ge=0.05, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def fits(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("局部识别范围超出页面")
        return self
