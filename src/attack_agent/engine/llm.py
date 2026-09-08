import json
import re

from loguru import logger
from ollama import AsyncClient
from tenacity import retry, stop_after_attempt, wait_fixed

from attack_agent.config import Settings, get_settings


class LLMError(Exception):
    pass


def extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    raw = match.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(raw.replace("'", '"'))
        except json.JSONDecodeError:
            return None


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.client = AsyncClient(host=self.settings.ollama_host)

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(1), reraise=True)
    async def chat_text(
        self, messages: list[dict[str, str]], temperature: float | None = None
    ) -> str:
        response = await self.client.chat(
            model=self.settings.model_name,
            messages=messages,
            options={
                "temperature": (
                    temperature
                    if temperature is not None
                    else self.settings.temperature
                )
            },
        )
        content = (
            response.message.content
            if hasattr(response, "message")
            else response["message"]["content"]
        )
        if not content or not content.strip():
            raise LLMError("empty response from model")
        return content.strip()

    async def chat_json(
        self, messages: list[dict[str, str]], temperature: float | None = None
    ) -> dict | None:
        content = await self.chat_text(messages, temperature)
        data = extract_json(content)
        if data is not None:
            return data
        logger.debug("json parse failed, retrying with correction prompt")
        retry_messages = [
            *messages,
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": "Respond with ONLY the corrected valid JSON object. No other text.",
            },
        ]
        content = await self.chat_text(retry_messages, temperature)
        return extract_json(content)

    async def list_models(self) -> list[str]:
        response = await self.client.list()
        names = []
        for model in getattr(response, "models", []):
            name = getattr(model, "model", None)
            if name:
                names.append(name)
        return names
