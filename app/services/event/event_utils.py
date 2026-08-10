"""Event Utility Module — Geocoding & Category Normalization."""

import logging
import re
import urllib.parse
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


def normalize_category_slug(raw_cat: str) -> str:
    """Normalize raw category string to standardized category slug."""
    if not raw_cat or not isinstance(raw_cat, str):
        return "general"
    c = raw_cat.lower().strip()
    if any(k in c for k in ["music", "concert", "dj", "band", "performance", "song", "acoustic"]):
        return "music"
    if any(k in c for k in ["nightlife", "party", "club", "bar", "cocktail", "lounge"]):
        return "nightlife"
    if any(k in c for k in ["food", "dining", "bazaar", "expo", "cuisine", "coffee", "tasting"]):
        return "food"
    if any(k in c for k in ["art", "culture", "exhibition", "museum", "gallery", "fashion"]):
        return "art"
    if any(k in c for k in ["tech", "business", "networking", "workshop", "conference"]):
        return "tech"
    if any(k in c for k in ["cinema", "movie", "film", "screening"]):
        return "cinema"
    if any(k in c for k in ["sport", "fitness", "run", "marathon", "match", "game"]):
        return "sports"
    if any(k in c for k in ["outdoor", "park", "tour", "hike", "nature"]):
        return "outdoor"
    return "general"


async def geocode_venue_osm(venue_name: Optional[str], sub_city: Optional[str]) -> Optional[str]:
    """Geocode venue using free OpenStreetMap Nominatim API with progressive fallbacks."""
    queries = []
    clean_venue = re.split(r'[,(]', venue_name)[0].strip() if venue_name else None

    if venue_name and venue_name.strip() and venue_name.lower() != "addis ababa":
        queries.append(f"{venue_name.strip()}, Addis Ababa, Ethiopia")
    if clean_venue and clean_venue != venue_name:
        queries.append(f"{clean_venue}, Addis Ababa, Ethiopia")
    if sub_city and sub_city.strip():
        queries.append(f"{sub_city.strip()}, Addis Ababa, Ethiopia")

    queries.append("Addis Ababa, Ethiopia")

    headers = {"User-Agent": "AddisEventBot/1.0 (contact@addisevents.et)"}

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            for q in queries:
                url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(q)}&format=json&limit=1"
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and isinstance(data, list) and len(data) > 0:
                        lat = data[0].get("lat")
                        lon = data[0].get("lon")
                        if lat and lon:
                            logger.info(f"OSM geocoded [{q}] -> {lat},{lon}")
                            return f"{lat},{lon}"
    except Exception as e:
        logger.warning(f"OSM geocoding failed: {e}")
    return "9.0320,38.7478"
