from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request

from app.cache import HazardCache
from app.handlers import handle_by_ids, handle_by_names
from app.llm import LLMClient
from app.models import HazardResponse
from app.pubchem import PubChemClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pubchem_client = PubChemClient()
    app.state.llm_client = LLMClient()
    app.state.cache = HazardCache()
    yield
    await app.state.llm_client.close()
    await app.state.pubchem_client.close()


app = FastAPI(
    title="Hazard API",
    description="Check if chemical compounds are hazardous using PubChem GHS data",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/hazards", response_model=HazardResponse)
async def get_hazards(
    request: Request,
    cids: str | None = Query(None, description="Comma-separated PubChem CIDs (e.g. 887,702,2244)"),
    names: str | None = Query(None, description="Comma-separated product names (e.g. methanol,ethanol)"),
) -> HazardResponse:
    if cids and names:
        raise HTTPException(status_code=422, detail="Provide either 'cids' or 'names', not both")
    if not cids and not names:
        raise HTTPException(status_code=422, detail="Provide either 'cids' or 'names'")

    if cids:
        try:
            parsed_cids = [int(c.strip()) for c in cids.split(",") if c.strip()]
        except ValueError:
            raise HTTPException(status_code=422, detail="All CIDs must be valid integers")

        if not parsed_cids:
            raise HTTPException(status_code=422, detail="At least one CID is required")

        return await handle_by_ids(parsed_cids, request.app.state.pubchem_client)

    parsed_names = [n.strip() for n in names.split(",") if n.strip()]
    if not parsed_names:
        raise HTTPException(status_code=422, detail="At least one name is required")

    return await handle_by_names(
        parsed_names,
        request.app.state.pubchem_client,
        request.app.state.llm_client,
        request.app.state.cache,
    )
