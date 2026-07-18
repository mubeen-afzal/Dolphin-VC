import pytest

from app.config import Settings
from app.errors import AppError
from app.services.llm import LLMGateway, Purpose


@pytest.mark.resilience
async def test_no_llm_credentials_degrades_with_machine_readable_code() -> None:
    gateway = LLMGateway(Settings(openai_api_key="", nvidia_nim_api_key=""))
    with pytest.raises(AppError) as captured:
        await gateway.complete(
            purpose=Purpose.EXTRACT,
            messages=[{"role": "user", "content": "extract"}],
            schema=None,
        )
    assert captured.value.code == "SOURCE_UNAVAILABLE"
    assert captured.value.status_code == 503
    await gateway.close()
