"""设置读写:GET 返回脱敏视图,PUT 自动跳过脱敏占位值。"""

from fastapi import APIRouter, Depends

from ..core.runtime import RuntimeSettingsStore
from ..schemas import SettingsIn
from .deps import get_runtime_settings

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def read_settings(rs: RuntimeSettingsStore = Depends(get_runtime_settings)):
    return rs.load_masked()


@router.put("/settings")
def update_settings(s: SettingsIn, rs: RuntimeSettingsStore = Depends(get_runtime_settings)):
    rs.save(s.model_dump())
    return rs.load_masked()
