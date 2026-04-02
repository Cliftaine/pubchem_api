from pydantic import BaseModel


class HazardInfo(BaseModel):
    signal_word: str | None = None
    hazard_statements: list[str] = []
    pictogram_urls: list[str] = []


class ProductResult(BaseModel):
    query: str | None = None
    identifier: str
    compound_name: str | None = None
    hazardous: bool
    hazard_info: HazardInfo | None = None
    error: str | None = None


class HazardResponse(BaseModel):
    results: list[ProductResult]
