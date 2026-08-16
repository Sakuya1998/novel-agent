"""部署级配置:只来自环境变量 / .env 文件,进程生命周期内不可变。

与「运行时设置」(LLM provider/model 等,存于 data/config.json,可在 Web 设置页热改)
明确分离:基础设施行为(鉴权、限流、日志、并发)由本模块管理。
"""

import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent.parent


class DeploySettings(BaseSettings):
    """部署配置,环境变量前缀 NOVEL_AGENT_。"""

    model_config = SettingsConfigDict(
        env_prefix="NOVEL_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "prod"  # dev | prod
    data_dir: Path = _ROOT / "data"

    # 访问鉴权:非空时所有 /api/* 请求必须携带 X-API-Key
    auth_key: str = ""
    # 允许跨域的来源,逗号分隔;留空不启用 CORS
    cors_origins: str = ""

    # 限流:格式 "请求数/窗口秒",仅对 /api/* 生效;留空禁用
    rate_limit: str = "240/60"

    # 请求体大小上限(MB):拦截声明超长的 body,防超大请求 DoS
    max_body_mb: int = 2

    # 日志
    log_level: str = "INFO"
    log_json: bool = False

    # LLM 调用治理
    llm_concurrency: int = 4
    llm_timeout: float = 300.0
    llm_max_retries: int = 2

    @field_validator("env")
    @classmethod
    def _check_env(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("dev", "prod"):
            raise ValueError("env 必须是 dev 或 prod")
        return v

    @field_validator("log_level")
    @classmethod
    def _check_level(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise ValueError("log_level 必须是 DEBUG/INFO/WARNING/ERROR")
        return v

    @field_validator("llm_concurrency")
    @classmethod
    def _check_concurrency(cls, v: int) -> int:
        if v < 1:
            raise ValueError("llm_concurrency 至少为 1")
        return v

    @field_validator("max_body_mb")
    @classmethod
    def _check_max_body(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_body_mb 至少为 1")
        return v

    @property
    def max_body_bytes(self) -> int:
        return self.max_body_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def parse_rate_limit(self) -> tuple[int, float] | None:
        """解析 '请求数/窗口秒',非法或为空返回 None(禁用)。"""
        text = (self.rate_limit or "").strip()
        if not text:
            return None
        try:
            count_s, window_s = text.split("/", 1)
            count, window = int(count_s), float(window_s)
        except ValueError:
            return None
        if count < 1 or window < 1:
            return None
        return count, window


def load_deploy_settings() -> DeploySettings:
    """读取部署配置,兼容旧变量名 NOVEL_AGENT_DATA。"""
    settings = DeploySettings()
    legacy_data = os.environ.get("NOVEL_AGENT_DATA")
    if legacy_data:
        settings = settings.model_copy(update={"data_dir": Path(legacy_data)})
    return settings
