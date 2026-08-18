"""全局配置管理。

按《小说创作Agent开发文档》7.3 节实现:环境变量 + .env 双通道,
风格档案 STYLE_PROFILES 供 SceneWriter / StyleEditor 引用。
"""

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()
BASE_DIR = Path(__file__).parent


class Config(BaseSettings):
    """应用配置:环境变量 > .env 文件 > 默认值。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 部署环境。开发/测试保持兼容；生产环境启动时会拒绝不安全认证配置。
    app_environment: Literal["development", "test", "production"] = "development"

    # 模型环境回退配置：仅在工作台尚未保存模型路由时使用
    llm_provider: Literal["openai", "anthropic"] = "openai"
    model_name: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4000
    model_timeout_seconds: float = 120.0
    model_retry_attempts: int = 2
    model_retry_base_delay: float = 0.5
    max_novel_tokens: int = 0  # 0 表示不限制

    # 后台任务租约：允许多进程部署时只有持有未过期租约的 Worker 执行任务
    run_job_lease_seconds: int = 60
    run_job_heartbeat_seconds: int = 15

    # 环境回退密钥；工作台中的 API Key 加密保存在 SQLite
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # 环境回退嵌入模型；工作台路由优先
    embedding_model: str = "text-embedding-3-small"

    # 数据库配置
    chroma_persist_dir: str = str(BASE_DIR / "memory" / "chroma_db")
    sqlite_db_path: str = str(BASE_DIR / "memory" / "novels.db")
    checkpoint_db_path: str = str(BASE_DIR / "memory" / "checkpoints.db")
    model_secret_key_path: str = str(BASE_DIR / "data" / "model-settings.key")
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 认证默认关闭以兼容旧 CLI/本地单用户部署；生产环境应显式开启。
    auth_enabled: bool = False
    auth_session_hours: int = 24 * 30
    auth_rate_limit_window_seconds: int = 60
    auth_rate_limit_max_attempts: int = 10
    sensitive_rate_limit_window_seconds: int = 60
    sensitive_rate_limit_max_attempts: int = 30

    # 导入安全：限制单个上传文件大小，避免压缩炸弹或意外大文件拖垮 API。
    max_import_bytes: int = 50 * 1024 * 1024
    background_transfer_bytes: int = 10 * 1024 * 1024
    transfer_dir: str = str(BASE_DIR / "data" / "transfers")
    runtime_backup_dir: str = str(BASE_DIR / "data" / "runtime-backups")
    backup_retention_count: int = 7

    # 生成控制
    max_chapter_words: int = 6000
    total_chapters: int = 10
    max_revision_attempts: int = 3
    quality_gate_threshold: float = 70.0

    # 默认风格
    default_style: str = "jin_yong"

    def ensure_dirs(self) -> None:
        """确保运行期目录存在。"""
        Path(self.chroma_persist_dir).mkdir(parents=True, exist_ok=True)
        Path(self.sqlite_db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.checkpoint_db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.model_secret_key_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.transfer_dir).mkdir(parents=True, exist_ok=True)
        Path(self.runtime_backup_dir).mkdir(parents=True, exist_ok=True)
        (BASE_DIR / "output").mkdir(parents=True, exist_ok=True)


def validate_production_config(config: Config) -> None:
    """生产模式下拒绝匿名认证、通配 CORS 或无效认证保护参数。"""
    if config.app_environment != "production":
        return
    errors: list[str] = []
    if not config.auth_enabled:
        errors.append("AUTH_ENABLED 必须为 true")
    origins = [origin.strip() for origin in config.frontend_origins.split(",") if origin.strip()]
    if "*" in origins:
        errors.append("FRONTEND_ORIGINS 不能包含通配符 *")
    if int(config.auth_session_hours) < 1:
        errors.append("AUTH_SESSION_HOURS 必须大于 0")
    if int(config.auth_rate_limit_window_seconds) < 10:
        errors.append("AUTH_RATE_LIMIT_WINDOW_SECONDS 不能小于 10")
    if not 1 <= int(config.auth_rate_limit_max_attempts) <= 1000:
        errors.append("AUTH_RATE_LIMIT_MAX_ATTEMPTS 必须在 1 到 1000 之间")
    if int(config.sensitive_rate_limit_window_seconds) < 10:
        errors.append("SENSITIVE_RATE_LIMIT_WINDOW_SECONDS 不能小于 10")
    if not 1 <= int(config.sensitive_rate_limit_max_attempts) <= 1000:
        errors.append("SENSITIVE_RATE_LIMIT_MAX_ATTEMPTS 必须在 1 到 1000 之间")
    if errors:
        raise RuntimeError("生产配置不安全: " + "; ".join(errors))


# ---------------------------------------------------------------------------
# 风格档案:SceneWriter 的核心控制参数(文档 3.5)
# 语法/句长/词汇/叙事/节奏 六维控制 + 示例,新增风格按 11.1 指南扩展
# ---------------------------------------------------------------------------
STYLE_PROFILES: dict[str, dict] = {
    "jin_yong": {
        "name": "金庸风格",
        "syntax": ["使用流畅的汉语语法", "多用逗号连接的复合句", "段落长短相间"],
        "sentence_length": "中等偏长,平均30-50字",
        "vocabulary": ["四字成语频繁使用", "书面语为主", "古典武侠术语"],
        "narrative_techniques": ["全知视角", "伏笔", "侧面烘托", "对比"],
        "pacing": "张弛有度,大场面与抒情交替",
        "examples": [
            "那少年长剑一挥,剑光如匹练般横贯长空,恍若银河倒泻。",
            "他心中一凛,暗想:此人内力之深,实已臻化境,我万万不是对手。",
            "夕阳西下,余晖洒满山谷,映得漫山红叶如火如荼,煞是壮观。",
        ],
    },
    "gu_long": {
        "name": "古龙风格",
        "syntax": ["短句为主", "大量换行", "少用复合句"],
        "sentence_length": "短促有力,平均10-20字",
        "vocabulary": ["简洁直白", "口语化", "偶尔诗化表达"],
        "narrative_techniques": ["悬念", "转折", "留白"],
        "pacing": "快节奏,持续紧张",
        "examples": [
            "刀很快。刀光一闪。人已倒下。",
            "夜很冷。风很冷。他的心更冷。",
            "天涯远不远?不远。人就在天涯,天涯怎么会远?",
        ],
    },
    "murakami": {
        "name": "村上春树风格",
        "syntax": ["使用流畅的日语式翻译腔", "大量比喻", "独特的观察视角"],
        "sentence_length": "中等,平均20-40字",
        "vocabulary": ["日常词汇", "音乐/文学/食品专有名词", "独特的比喻"],
        "narrative_techniques": ["第一人称", "超现实元素", "细致的日常描写"],
        "pacing": "舒缓,注重氛围和心理",
        "examples": [
            "如同置身于深海般的孤独感,将我轻轻包裹。",
            "她像秋日的午后一样,安静而透明。",
            "不可思议的是,那旋律一旦响起,我便再也无法逃避自己的记忆。",
        ],
    },
    "yu_hua": {
        "name": "余华风格",
        "syntax": ["朴素直接的语法", "少修辞", "多用短句和白描"],
        "sentence_length": "简短,平均10-25字",
        "vocabulary": ["朴素", "民间词汇", "直白有力"],
        "narrative_techniques": ["零度叙事", "黑色幽默", "残酷现实"],
        "pacing": "冷静克制,暗流涌动",
        "examples": [
            "他活着,像一头牲口那样活着。",
            "那年冬天,我爷爷死了,死得很平静。",
            "月光照在路上,像是撒满了盐。",
        ],
    },
}


def get_style_prompt(style_name: str) -> str:
    """将风格档案转换为可嵌入 Prompt 的文本块。

    Args:
        style_name: 风格标识(STYLE_PROFILES 的 key)

    Returns:
        拼接好的风格描述文本;未知风格回退到默认风格并给出提示行。
    """
    profile = STYLE_PROFILES.get(style_name)
    if profile is None:
        profile = STYLE_PROFILES[Config().default_style]
        header = f"# 风格: {profile['name']}(注意:未知风格 {style_name!r},已回退到默认)"
    else:
        header = f"# 风格: {profile['name']}"

    lines = [
        header,
        f"## 语法规则: {'; '.join(profile['syntax'])}",
        f"## 句子长度: {profile['sentence_length']}",
        f"## 词汇选择: {'; '.join(profile['vocabulary'])}",
        f"## 叙事技巧: {'; '.join(profile['narrative_techniques'])}",
        f"## 节奏: {profile['pacing']}",
        "## 风格示例:",
    ]
    lines += [f"- {e}" for e in profile["examples"]]
    return "\n".join(lines)


def load_prompt(name: str) -> str:
    """加载 prompts/ 目录下的模板文件(PromptManager 便捷入口)。"""
    path = BASE_DIR / "prompts" / f"{name}.txt"
    return path.read_text(encoding="utf-8")

