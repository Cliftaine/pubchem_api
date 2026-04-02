import json

import httpx

from app.config import config

_llm_cfg = config["llm"]

SYSTEM_PROMPT = """You are a chemistry expert that translates common, commercial, or non-English substance names
into their standard English chemical compound names as recognized by PubChem.

Rules:
1. Respond ONLY with a valid JSON object — no explanation, no markdown.
2. Each key is the original name exactly as given.
3. Each value is the standard English chemical name, or null if you cannot determine it.
4. Prefer IUPAC or most common PubChem name (e.g. "acetylsalicylic acid" over "aspirin").

Examples:

Input:  ["agua oxigenada", "lejía", "bicarbonato", "rubbing alcohol", "Kochsalz"]
Output: {"agua oxigenada": "hydrogen peroxide", "lejía": "sodium hypochlorite", "bicarbonato": "sodium bicarbonate", "rubbing alcohol": "isopropanol", "Kochsalz": "sodium chloride"}

Input:  ["vinagre", "cal viva", "soda cáustica"]
Output: {"vinagre": "acetic acid", "cal viva": "calcium oxide", "soda cáustica": "sodium hydroxide"}

Names to resolve:"""


class LLMClient:
    """LLM client for resolving chemical names.
    """

    def __init__(self) -> None:
        self._provider = _llm_cfg.get("provider", "")
        self._api_key = _llm_cfg.get("api_key", "")
        self._model = _llm_cfg.get("model", "")
        self._http = httpx.AsyncClient(timeout=30.0)
        self._configured = bool(self._provider and self._api_key)

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def close(self) -> None:
        await self._http.aclose()

    async def resolve_names(self, names: list[str]) -> dict[str, str | None]:
        """Map common/commercial names to standard chemical names via LLM.

        Returns a dict mapping each name to its suggested chemical name,
        or None if the model couldn't resolve it.

        Raises LLMNotConfiguredError if provider/api_key are not set.
        Raises LLMRequestError if the API call fails.
        """
        if not self._configured:
            raise LLMNotConfiguredError(
                "LLM is not configured. Set provider and api_key in config.yaml "
                "(see config.example.yaml for reference)"
            )

        if self._provider == "groq":
            return await self._call_groq(names)
        elif self._provider == "gemini":
            return await self._call_gemini(names)
        else:
            raise LLMNotConfiguredError(f"Unknown LLM provider: '{self._provider}'. Use 'groq' or 'gemini'")

    async def _call_groq(self, names: list[str]) -> dict[str, str | None]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(names)},
            ],
            "temperature": 0.0,
        }

        response = await self._http.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        return _parse_json_response(text)

    async def _call_gemini(self, names: list[str]) -> dict[str, str | None]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}"
            f":generateContent?key={self._api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n{json.dumps(names)}"}]}],
            "generationConfig": {"temperature": 0.0},
        }

        response = await self._http.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_json_response(text)


def _parse_json_response(text: str) -> dict[str, str | None]:
    """Extract JSON from LLM response, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


class LLMNotConfiguredError(Exception):
    pass


class LLMRequestError(Exception):
    pass
