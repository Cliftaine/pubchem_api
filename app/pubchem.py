import asyncio
import time

import httpx

from app.config import config
from app.models import HazardInfo, ProductResult

_pubchem_cfg = config["pubchem"]

PUBCHEM_PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


class PubChemClient:
    def __init__(self) -> None:
        self._base_url = _pubchem_cfg["base_url"]
        self._http = httpx.AsyncClient(timeout=_pubchem_cfg["timeout"])
        self._semaphore = asyncio.Semaphore(_pubchem_cfg["max_concurrent_requests"])
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._http.aclose()

    async def get_ghs_classification(self, cid: int) -> ProductResult:
        url = f"{self._base_url}/{cid}/JSON"
        params = {
            "response_type": "display",
            "heading": "GHS Classification",
        }

        try:
            await self._throttle()
            response = await self._http.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            hazard_info = _parse_ghs_data(data)
            compound_name = data.get("Record", {}).get("RecordTitle")

            is_hazardous = hazard_info is not None and bool(hazard_info.hazard_statements)
            return ProductResult(
                identifier=str(cid),
                compound_name=compound_name,
                hazardous=is_hazardous,
                hazard_info=hazard_info,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                error_msg = f"Compound CID {cid} not found"
            else:
                error_msg = f"PubChem API error: {e.response.status_code}"
            return ProductResult(identifier=str(cid), hazardous=False, error=error_msg)

        except httpx.RequestError as e:
            return ProductResult(
                identifier=str(cid),
                hazardous=False,
                error=f"Request failed: {e}",
            )

    async def resolve_name_to_cid(self, name: str) -> int | None:
        """Try to resolve a compound name to a PubChem CID. Returns None if not found."""
        url = f"{PUBCHEM_PUG_REST}/compound/name/{name}/cids/JSON"
        try:
            await self._throttle()
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
            cids = data.get("IdentifierList", {}).get("CID", [])
            return cids[0] if cids else None
        except (httpx.HTTPStatusError, httpx.RequestError):
            return None

    async def _throttle(self) -> None:
        async with self._semaphore:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_request_time
                if elapsed < 0.2:
                    await asyncio.sleep(0.2 - elapsed)
                self._last_request_time = time.monotonic()


def _parse_ghs_data(data: dict) -> HazardInfo | None:
    try:
        sections = data["Record"]["Section"]
    except (KeyError, TypeError):
        return None

    # Navigate to the GHS Classification information items
    information_items = _find_information_items(sections)
    if not information_items:
        return None

    signal_word: str | None = None
    hazard_statements: list[str] = []
    pictogram_urls: list[str] = []

    for item in information_items:
        name = item.get("Name", "")

        if name == "Pictogram(s)":
            for swm in item.get("Value", {}).get("StringWithMarkup", []):
                for markup in swm.get("Markup", []):
                    url = markup.get("URL")
                    if url:
                        pictogram_urls.append(url)

        elif name == "Signal":
            swm_list = item.get("Value", {}).get("StringWithMarkup", [])
            if swm_list:
                signal_word = swm_list[0].get("String")

        elif name == "GHS Hazard Statements":
            for swm in item.get("Value", {}).get("StringWithMarkup", []):
                statement = swm.get("String")
                if statement:
                    hazard_statements.append(statement)

    if not signal_word and not hazard_statements and not pictogram_urls:
        return None

    return HazardInfo(
        signal_word=signal_word,
        hazard_statements=list(dict.fromkeys(hazard_statements)),
        pictogram_urls=list(dict.fromkeys(pictogram_urls)),
    )


def _find_information_items(sections: list[dict]) -> list[dict] | None:
    """Walk the nested section structure to find Information items."""
    for section in sections:
        # Check if this section has Information items directly
        if "Information" in section:
            return section["Information"]
        # Otherwise recurse into sub-sections
        sub_sections = section.get("Section", [])
        if sub_sections:
            result = _find_information_items(sub_sections)
            if result:
                return result
    return None
