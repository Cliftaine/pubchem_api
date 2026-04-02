import asyncio

from app.cache import HazardCache
from app.llm import LLMClient, LLMNotConfiguredError
from app.models import HazardResponse, ProductResult
from app.pubchem import PubChemClient


async def handle_by_ids(cids: list[int], client: PubChemClient) -> HazardResponse:
    tasks = [client.get_ghs_classification(cid) for cid in cids]
    results = await asyncio.gather(*tasks)
    return HazardResponse(results=list(results))


async def handle_by_names(
    names: list[str], pubchem: PubChemClient, llm: LLMClient, cache: HazardCache
) -> HazardResponse:
    # Step 0: Check cache first
    cached_results: dict[str, ProductResult] = {}
    uncached: list[str] = []

    for name in names:
        hit = cache.get(name)
        if hit is not None:
            cached_results[name] = hit
        else:
            uncached.append(name)

    # If everything was cached, return immediately
    if not uncached:
        results = [cached_results[name] for name in names]
        return HazardResponse(results=results)

    # Step 1: Try direct PubChem name lookup for uncached names
    resolve_tasks = [pubchem.resolve_name_to_cid(name) for name in uncached]
    cids = await asyncio.gather(*resolve_tasks)

    resolved: dict[str, int] = {}
    unresolved: list[str] = []

    for name, cid in zip(uncached, cids):
        if cid is not None:
            resolved[name] = cid
        else:
            unresolved.append(name)

    # Step 2: Use LLM to suggest chemical names for unresolved products
    llm_error: str | None = None
    if unresolved:
        try:
            suggestions = await llm.resolve_names(unresolved)
            retry_tasks = []
            retry_names = []

            for name in unresolved:
                suggested = suggestions.get(name)
                if suggested:
                    retry_names.append(name)
                    retry_tasks.append(pubchem.resolve_name_to_cid(suggested))

            if retry_tasks:
                retry_cids = await asyncio.gather(*retry_tasks)
                for name, cid in zip(retry_names, retry_cids):
                    if cid is not None:
                        resolved[name] = cid

        except LLMNotConfiguredError as e:
            llm_error = str(e)
        except Exception:
            llm_error = "LLM request failed — only direct PubChem matches are available"

    # Fetch hazard data for all resolved CIDs
    hazard_tasks = {
        name: pubchem.get_ghs_classification(cid) for name, cid in resolved.items()
    }
    if hazard_tasks:
        hazard_results = await asyncio.gather(*hazard_tasks.values())
        hazard_by_name = dict(zip(hazard_tasks.keys(), hazard_results))
    else:
        hazard_by_name = {}

    # Store successful lookups in cache
    for name, result in hazard_by_name.items():
        result.query = name
        cache.put(name, result)

    # Build final results preserving original order
    results: list[ProductResult] = []
    for name in names:
        if name in cached_results:
            results.append(cached_results[name])
        elif name in hazard_by_name:
            results.append(hazard_by_name[name])
        else:
            error = llm_error or f"Could not resolve '{name}' to a PubChem compound"
            results.append(ProductResult(
                query=name,
                identifier=name,
                hazardous=False,
                error=error,
            ))

    return HazardResponse(results=results)
