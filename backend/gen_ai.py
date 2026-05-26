from main import settings
from typing import Optional, List

import logging
import requests
from pydantic import BaseModel

# Only import genai and types if needed for LLM integration
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CurrencyConversionResponse(BaseModel):
    # {
    #     "amount": 1,
    #     "base": "EUR",
    #     "date": "2026-01-19",
    #     "rates": {
    #         "USD": 1.1631
    #     }
    # }
    amount: float
    base: str
    date: str
    rates: dict[str, float]

class GeoLocationResult(BaseModel):
    place_id: int
    display_name: str
    lat: str
    lon: str

class SQLGenerationResponse(BaseModel):
    thought_process: str
    sql_query: str

def get_currency_conversion_rate(from_currency: str, to_currency: str) -> CurrencyConversionResponse:
    """
    Calls Frankfurter API to get the latest currency conversion rate from from_currency to to_currency.
    """
    url = "https://api.frankfurter.dev/v1/latest"
    params = {
        "base": from_currency.upper(),
        "symbols": to_currency.upper()
    }
    try:
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Currency conversion API response: {data}")
        return CurrencyConversionResponse(**data)
    except Exception as e:
        logger.error(f"Error fetching currency conversion rate: {e}")
        raise

def get_geo_location(place_name: str) -> Optional[GeoLocationResult]:
    """
    Calls OpenStreetMap Nominatim API to get location coordinates for a place name.
    Returns the first result as GeoLocationResult, or None if not found.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": place_name,
        "format": "json"
    }
    try:
        resp = requests.get(url, params=params, timeout=5, headers={"User-Agent": "bcf-2026-hackathon/1.0"})
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Geo location API response: {data}")
        if data:
            return GeoLocationResult(**data[0])
        return None
    except Exception as e:
        logger.error(f"Error fetching geo location: {e}")
        raise

def init_genai_conversation(question: str, llm: str, schema_context: str) -> str:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    system_prompt = f"""
    You are an expert PostgreSQL DBA running inside an automated database evaluation harness. 
    Your objective is to generate an accurate, highly-optimized, read-only SQL query matching the user's question.
    
    {schema_context}
    
    Strict Operational Rules:
    1. Base your query entirely on the DYNAMIC DATABASE SCHEMA LAYOUT and TABLE RELATIONSHIPS provided above. 
    2. Do not hallucinate column names or guess relationship paths. Use the designated JOIN keys explicitly map paths.
    3. Return ONLY valid JSON matching the requested response schema structure. Do not output markdown text block formatting markers (e.g. ```json).
    4. Current relative date conditions must assume the current year context is 2026.
    """

    prompt = f"Convert this request to SQL: {question}"

    response = client.models.generate_content(
        model=llm,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[
                get_geo_location,
                get_currency_conversion_rate
            ],
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=SQLGenerationResponse,
            temperature=0.0
        )
    )

    result = SQLGenerationResponse.model_validate_json(response.text)

    logger.info(f"LLM response: {result.thought_process}")

    return result.sql_query