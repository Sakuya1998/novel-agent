"""测试夹具:隔离的临时数据目录 + mock provider 的应用实例。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import DeploySettings
from app.main import create_app


def make_deploy(tmp_path, **overrides) -> DeploySettings:
    """构建测试部署配置:_env_file=None 隔离本地 .env 污染。"""
    fields = dict(
        env="dev",
        data_dir=tmp_path / "data",
        auth_key="",
        rate_limit="",
        log_level="WARNING",
        _env_file=None,
    )
    fields.update(overrides)
    return DeploySettings(**fields)


def make_app(tmp_path, **overrides):
    app = create_app(make_deploy(tmp_path, **overrides))
    app.state.runtime_settings.save({"provider": "mock", "model": "mock", "api_key": ""})
    return app


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
