"""门户新手引导模型

引导分四步：建项目 → 填关键词 → 选话术 → 启动任务。
目标是让客户 5 分钟内跑出第一个结果，所以每一步都得能落库，
中途关掉页面再进来要能接着走，不能从头填。
"""

from typing import List, Optional

from pydantic import BaseModel


class OnboardingStepItem(BaseModel):
    """单个步骤的展示信息"""

    index: int
    key: str
    title: str
    desc: str
    done: bool = False


class PresetScriptOption(BaseModel):
    """预置话术选项：只给名称与开头一段，不推全文"""

    id: int
    name: str
    preview: str = ''


class PlatformOption(BaseModel):
    id: int
    name: str
    code: str


class OnboardingStatus(BaseModel):
    """引导状态。前端据此决定要不要跳引导页、跳转到第几步"""

    done: bool
    current_step: int
    total_steps: int = 4
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    steps: List[OnboardingStepItem] = []
    platforms: List[PlatformOption] = []
    presets: List[PresetScriptOption] = []


class OnboardingProjectRequest(BaseModel):
    name: str
    platform_id: int
    preset_template_id: Optional[int] = None


class OnboardingKeywordsRequest(BaseModel):
    keywords: List[str]
    priority: int = 1


class OnboardingScriptRequest(BaseModel):
    template_id: int


class OnboardingLaunchRequest(BaseModel):
    limit: int = 240
    task_type: str = 'scrape'


class OnboardingStepResult(BaseModel):
    """每一步提交后的推进结果"""

    done: bool
    current_step: int
    project_id: Optional[int] = None
    message: str = ''
