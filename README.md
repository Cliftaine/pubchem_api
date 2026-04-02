# PubChem Hazard API

API to check whether chemical products or compounds are hazardous using GHS data from [PubChem](https://pubchem.ncbi.nlm.nih.gov/).

Supports lookup by CID (PubChem identifier) and by common or commercial name in any language, using an LLM as a fallback to translate names that PubChem does not recognize directly.

## Requirements

- Python >= 3.11

## Installation and setup

```bash
# Clone and install dependencies
pip install -e .

# Run the server
python -m app
```

The server starts by default on `http://localhost:8080` (configurable in `config.yaml`).

## LLM configuration (Groq)

The API uses an LLM to resolve names that PubChem cannot find directly. 
We use **Groq** with the `llama-3.3-70b-versatile` model.

To enable the LLM, set your Groq API key in `config.yaml`:

```yaml
llm:
  provider: "groq"
  api_key: "your-api-key-here"  # <-- paste your key here
  model: "llama-3.3-70b-versatile"
```

To generate your own free key:

1. Create an account at [console.groq.com](https://console.groq.com)
2. Go to **API Keys** and create a new one
3. Paste the key in `config.yaml` as shown above

Groq offers a free tier with 30 requests per minute, no credit card required.

## Interactive usage with Swagger UI

Once the server is running, you can interact with the API from the browser at:

```
http://localhost:8080/docs
```

Swagger UI lets you try the endpoint directly. The available endpoint is:

### `GET /hazards`

| Parameter | Type   | Description                              |
|-----------|--------|------------------------------------------|
| `cids`    | string | Comma-separated PubChem CIDs             |
| `names`   | string | Comma-separated product names            |

Exactly **one** of the two must be provided, not both.

### Why query parameters instead of a JSON body?

While it is technically possible to send a JSON body in a GET request, doing so is not considered good practice. The HTTP/1.1 spec does not forbid it, but many clients, proxies, and caching layers may ignore or discard the body of a GET request. Additionally, frameworks like FastAPI and tools like Swagger UI do not support GET request bodies well.

The standard approach for sending lists in a GET request is through **query parameters** — either as comma-separated values (`?cids=887,702,2244`) or as repeated parameters (`?cids=887&cids=702&cids=2244`). This implementation uses comma-separated values as it is more concise and readable.

### Examples

**Search by CIDs:**
```
GET /hazards?cids=887,2244
```

**Search by chemical names (direct PubChem match):**
```
GET /hazards?names=methanol,aspirin
```

**Search by common names or other languages (uses LLM as fallback):**
```
GET /hazards?names=agua oxigenada,lejia,rubbing alcohol
```

**Example response:**
```json
{
  "results": [
    {
      "query": "agua oxigenada",
      "identifier": "784",
      "compound_name": "Hydrogen Peroxide",
      "hazardous": true,
      "hazard_info": {
        "signal_word": "Danger",
        "hazard_statements": [
          "H271: May cause fire or explosion; strong Oxidizer",
          "H302: Harmful if swallowed",
          "H314: Causes severe skin burns and eye damage",
          "H332: Harmful if inhaled"
        ],
        "pictogram_urls": [
          "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS03.svg",
          "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS05.svg",
          "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS07.svg"
        ]
      },
      "error": null
    }
  ]
}
```

## Architecture

```
pubchem_api/
├── config.yaml              # Server, PubChem and LLM configuration
├── pyproject.toml            # Project dependencies
├── cache.pickle              # Auto-generated cache persistence (gitignored)
├── app/
│   ├── __main__.py           # Entry point: python -m app
│   ├── main.py               # FastAPI app, endpoint and lifespan
│   ├── config.py             # Loads config.yaml
│   ├── models.py             # Pydantic schemas (HazardInfo, ProductResult)
│   ├── pubchem.py            # Async client for PubChem PUG-View and PUG-REST
│   ├── handlers.py           # Business logic (handle_by_ids, handle_by_names)
│   ├── llm.py                # Multi-provider LLM client (Groq / Gemini)
│   └── cache.py              # In-memory LRU cache with pickle persistence
```

### Name resolution flow

When searching by names, the system checks the cache first and then follows a two-pass resolution process for any uncached names:

```
User-provided names
       │
       ▼
  ┌─────────────────────┐
  │  Step 1: Cache check  │  Returns immediately for previously
  │  (in-memory LRU)    │  resolved names — no API calls needed
  └────────┬────────────┘
           │
     Uncached names
           │
           ▼
  ┌─────────────────────┐
  │  Step 2: PubChem    │  Looks up each name directly in PubChem
  │  (direct lookup)    │  e.g. "methanol" → CID 887 ✓
  └────────┬────────────┘
           │
     Unresolved names
           │
           ▼
  ┌─────────────────────┐
  │  Step 3: LLM        │  Translates common/commercial/non-English names
  │  (fallback)         │  into standard English chemical names
  │                     │  e.g. "agua oxigenada" → "hydrogen peroxide"
  └────────┬────────────┘
           │
     Translated names
           │
           ▼
  ┌─────────────────────┐
  │  PubChem retry      │  Looks up the LLM-suggested names
  │                     │  e.g. "hydrogen peroxide" → CID 784 ✓
  └────────┬────────────┘
           │
     All resolved CIDs
           │
           ▼
  ┌─────────────────────┐
  │  GHS lookup         │  Fetches hazard classification
  │  (PubChem PUG-View) │  for each resolved CID
  └────────┬────────────┘
           │
     Successful results
           │
           ▼
  ┌─────────────────────┐
  │  Cache store        │  Saves results to cache for future
  │  (pickle to disk)   │  lookups (max 100 entries, LRU eviction)
  └─────────────────────┘
```

### Why an LLM?

PubChem is a scientific database that uses standard English chemical nomenclature. When a user searches for "agua oxigenada" or "lejia", PubChem returns no results because it does not handle commercial names or names in other languages.

The LLM acts as an intelligent translation layer that converts these names into their chemical equivalent recognized by PubChem. This makes the API accessible to non-specialist users who use common terminology instead of IUPAC names.

If the LLM is not configured or fails, the API continues to work: it returns results for names that PubChem recognizes directly and reports a descriptive error for those it could not resolve.

### Caching strategy

The API includes an in-memory LRU cache to avoid redundant API calls and LLM requests for previously resolved names:

- **Max 100 entries** — least recently used entries are evicted when the limit is reached
- **Case insensitive** — "Methanol" and "methanol" share the same cache entry
- **Pickle persistence** — the cache is saved to `cache.pickle` on every write and loaded automatically on startup, so results survive server restarts
- **Cache priority** — the cache is checked **before** any PubChem or LLM call; cached results are returned immediately with zero network overhead
- **Only successful lookups** are cached — errors and unresolved names are not stored, so they can be retried on subsequent requests
