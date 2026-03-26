import httpx
import asyncio
import math
import os
from fastapi import APIRouter, HTTPException, Query
from db.connection import db
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
FSQ_API_KEY = os.getenv("FSQ_API_KEY", "")
FSQ_BASE = "https://api.foursquare.com/v3"
FSQ_HEADERS = {
    "Authorization": FSQ_API_KEY,
    "Accept": "application/json",
}

router = APIRouter(prefix="/places", tags=["Places"])

places_collection = db["places_cache"]

# ── City bounding boxes ──────────────────────────────────────────────────────
CITY_BBOX = {
    "mumbai":    (18.8900, 72.7760, 19.2720, 73.0000),
    "delhi":     (28.4040, 76.8380, 28.8830, 77.3470),
    "bangalore": (12.8340, 77.4600, 13.1440, 77.7840),
    "chennai":   (12.9160, 80.1730, 13.2300, 80.3290),
    "hyderabad": (17.2350, 78.2690, 17.5540, 78.6280),
    "pune":      (18.4140, 73.7560, 18.6360, 73.9840),
    "kolkata":   (22.4530, 88.2420, 22.6590, 88.4760),
    "jaipur":    (26.8000, 75.7200, 27.0800, 76.0000),
    "goa":       (15.2120, 73.9010, 15.5160, 74.1980),
}

CATEGORY_QUERIES = {
    "Sights": '[tourism~"attraction|museum|monument|viewpoint|theme_park"]',
    "Cafés":  '[amenity~"cafe|coffee_shop"]',
    "Food":   '[amenity~"restaurant|fast_food|food_court"]',
    "Shops":  '[shop~"mall|supermarket|clothes|shoes|jewelry"]',
}

# ── Hidden gem OSM tags — lesser known, off-the-beaten-path places ──────────
GEM_TAGS = [
    '[tourism="artwork"]',
    '[tourism="picnic_site"]',
    '[tourism="garden"]',
    '[historic~"memorial|ruins|building|wayside_shrine|fort"]',
    '[leisure~"nature_reserve|park|garden"]',
    '[natural~"cave_entrance|spring|waterfall|cliff|beach"]',
    '[amenity~"place_of_worship|library|community_centre"]',
]

def gem_vibe(tags: dict) -> str:
    if tags.get("tourism") == "artwork":           return "Street Art"
    if tags.get("tourism") == "picnic_site":       return "Locals Only"
    if tags.get("tourism") == "garden":            return "Hidden Garden"
    if tags.get("historic"):                       return "Forgotten History"
    if tags.get("natural") in ("waterfall","spring"): return "Natural Wonder"
    if tags.get("natural") == "cave_entrance":     return "Secret Cave"
    if tags.get("natural") == "beach":             return "Secret Beach"
    if tags.get("leisure") == "nature_reserve":    return "Nature Reserve"
    if tags.get("amenity") == "place_of_worship":  return "Sacred Spot"
    if tags.get("amenity") == "library":           return "Hidden Knowledge"
    return "Off The Map"


# ── Haversine distance in km ────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


# ============================================================
# FOURSQUARE — venue search, photos, details
# ============================================================
async def fetch_fsq_venue(place_name: str, lat: float, lon: float) -> dict | None:
    """Search Foursquare for a venue by name near coordinates."""
    if not FSQ_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10, headers=FSQ_HEADERS) as client:
            resp = await client.get(
                f"{FSQ_BASE}/places/search",
                params={
                    "query": place_name,
                    "ll": f"{lat},{lon}",
                    "radius": 500,
                    "limit": 1,
                    "fields": "fsq_id,name,description,hours,tel,website,rating,price,photos,categories",
                },
            )
        if resp.status_code != 200 or not resp.text.strip():
            return None
        results = resp.json().get("results", [])
        if not results:
            return None
        return results[0]
    except Exception as e:
        print(f"⚠️ FSQ venue search failed for '{place_name}': {e}")
        return None


async def fetch_fsq_photos(fsq_id: str, limit: int = 5) -> list[str]:
    """Fetch photo URLs for a Foursquare venue."""
    if not FSQ_API_KEY or not fsq_id:
        return []
    try:
        async with httpx.AsyncClient(timeout=10, headers=FSQ_HEADERS) as client:
            resp = await client.get(
                f"{FSQ_BASE}/places/{fsq_id}/photos",
                params={"limit": limit},
            )
        if resp.status_code != 200 or not resp.text.strip():
            return []
        photos = resp.json()
        urls = []
        for p in photos:
            prefix = p.get("prefix", "")
            suffix = p.get("suffix", "")
            if prefix and suffix:
                urls.append(f"{prefix}800x600{suffix}")
        return urls
    except Exception as e:
        print(f"⚠️ FSQ photos failed for '{fsq_id}': {e}")
        return []


async def fetch_fsq_place_data(
    place_name: str, lat: float, lon: float, city: str
) -> dict:
    """
    Fetch all Foursquare data for a place.
    Returns dict with: images, description, hours, phone, website, rating, price
    Falls back to Wikipedia for description if FSQ has none.
    """
    result = {
        "images": [],
        "description": "",
        "hours": "",
        "phone": "",
        "website": "",
        "rating": None,
        "price": "",
    }

    if not FSQ_API_KEY or lat == 0 or lon == 0:
        return result

    venue = await fetch_fsq_venue(place_name, lat, lon)
    if not venue:
        print(f"⚠️ FSQ: no venue found for '{place_name}'")
        return result

    fsq_id = venue.get("fsq_id", "")
    print(f"✅ FSQ found: '{venue.get('name')}' for '{place_name}'")

    # Description
    result["description"] = venue.get("description", "")

    # Hours
    hours_obj = venue.get("hours", {})
    if hours_obj:
        display = hours_obj.get("display", "")
        if display:
            result["hours"] = display

    # Contact
    result["phone"] = venue.get("tel", "")
    result["website"] = venue.get("website", "")

    # Rating (out of 10 → convert to readable)
    rating = venue.get("rating")
    if rating:
        result["rating"] = round(rating / 2, 1)  # convert to 5-star scale

    # Price tier
    price = venue.get("price")
    if price:
        result["price"] = "₹" * price  # 1-4 rupee symbols

    # Photos
    if fsq_id:
        result["images"] = await fetch_fsq_photos(fsq_id, limit=5)

    return result


# ============================================================
# WIKIMEDIA — single thumbnail image (fallback for landmarks)
# ============================================================
async def fetch_wikimedia_image(place_name: str, city: str) -> str | None:
    headers = {
        "User-Agent": "GoViaApp/1.0 (travel app; contact@govia.app) httpx/0.24",
        "Accept": "application/json",
    }
    REJECT_TITLES = [city.lower(), "india", "maharashtra", "list of", "district"]
    place_words = [w for w in place_name.lower().split() if len(w) > 3]
    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            search_resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": f"{place_name} {city}",
                    "format": "json",
                    "srlimit": 5,
                },
            )
            if not search_resp.text.strip():
                return None
            results = search_resp.json().get("query", {}).get("search", [])
            if not results:
                return None

            # ✅ Pick most relevant title — same logic as description
            page_title = None
            for r in results:
                title_lower = r["title"].lower()
                if any(reject == title_lower for reject in REJECT_TITLES):
                    continue
                if place_words and not any(w in title_lower for w in place_words):
                    continue
                page_title = r["title"]
                break

            if not page_title:
                return None

            images_resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "titles": page_title,
                    "prop": "pageimages",
                    "pithumbsize": 600,
                    "format": "json",
                },
            )
            if not images_resp.text.strip():
                return None
            pages = images_resp.json().get("query", {}).get("pages", {})
            for page in pages.values():
                url = page.get("thumbnail", {}).get("source")
                if url:
                    return url
        return None
    except Exception as e:
        print(f"⚠️ Wikimedia image failed for '{place_name}': {e}")
        return None



# ============================================================
# WIKIPEDIA — strict thumbnail (only exact title match)
# ============================================================
async def fetch_strict_wikipedia_image(place_name: str, city: str) -> str | None:
    headers = {
        "User-Agent": "GoViaApp/1.0 (travel app; contact@govia.app) httpx/0.24",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": f"{place_name} {city}",
                    "format": "json",
                    "srlimit": 5,
                },
            )
            if not resp.text.strip():
                return None
            results = resp.json().get("query", {}).get("search", [])
            if not results:
                return None

            # Only accept if article title closely matches place name
            page_title = None
            name_lower = place_name.lower()
            for r in results:
                title_lower = r["title"].lower()
                if name_lower == title_lower or name_lower in title_lower:
                    page_title = r["title"]
                    break

            if not page_title:
                print(f"No exact Wikipedia match for {place_name!r}")
                return None

            img_resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "titles": page_title,
                    "prop": "pageimages",
                    "pithumbsize": 800,
                    "format": "json",
                },
            )
            if not img_resp.text.strip():
                return None
            pages = img_resp.json().get("query", {}).get("pages", {})
            for page in pages.values():
                url = page.get("thumbnail", {}).get("source")
                if url:
                    print(f"Wikipedia image for {place_name!r}: {page_title}")
                    return url
        return None
    except Exception as e:
        print(f"Strict Wikipedia image failed for {place_name!r}: {e}")
        return None

# ============================================================
# WIKIMEDIA — multiple images for details page
# ============================================================
async def fetch_wikimedia_images(place_name: str, city: str, max_images: int = 5) -> list[str]:
    # ✅ Proper browser-like headers — prevents empty 200 responses from Wikipedia
    headers = {
        "User-Agent": "GoViaApp/1.0 (travel app; contact@govia.app) httpx/0.24",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            # Step 1: Find the Wikipedia page
            search_resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": f"{place_name} {city}",
                    "format": "json",
                    "srlimit": 1,
                },
            )
            if not search_resp.text.strip():
                print(f"⚠️ Empty search response for '{place_name}'")
                return []

            results = search_resp.json().get("query", {}).get("search", [])
            if not results:
                return []

            page_title = results[0]["title"]
            print(f"📖 Wikipedia page for '{place_name}': {page_title}")

            # Step 2: Get all images on the page
            images_resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "titles": page_title,
                    "prop": "images",
                    "format": "json",
                    "imlimit": 20,
                },
            )
            if not images_resp.text.strip():
                thumb = await fetch_wikimedia_image(place_name, city)
                return [thumb] if thumb else []

            pages = images_resp.json().get("query", {}).get("pages", {})
            image_titles = []
            for page in pages.values():
                for img in page.get("images", []):
                    title = img.get("title", "")
                    if any(skip in title.lower() for skip in
                           ["icon", "flag", "logo", "symbol", "map", "commons",
                            "wikimedia", "edit", "arrow", "button", "stub"]):
                        continue
                    if title.lower().endswith((".jpg", ".jpeg", ".png")):
                        image_titles.append(title)

            if not image_titles:
                thumb = await fetch_wikimedia_image(place_name, city)
                return [thumb] if thumb else []

            # Step 3: Get actual URLs for each image title
            urls = []
            for title in image_titles[:max_images]:
                try:
                    url_resp = await client.get(
                        "https://en.wikipedia.org/w/api.php",
                        params={
                            "action": "query",
                            "titles": title,
                            "prop": "imageinfo",
                            "iiprop": "url|thumburl",
                            "iiurlwidth": 800,
                            "format": "json",
                        },
                    )
                    if not url_resp.text.strip():
                        continue
                    url_pages = url_resp.json().get("query", {}).get("pages", {})
                    for p in url_pages.values():
                        info = p.get("imageinfo", [])
                        if info:
                            thumb_url = info[0].get("thumburl") or info[0].get("url")
                            if thumb_url:
                                urls.append(thumb_url)
                except Exception:
                    continue

            # ✅ Fallback to single thumbnail if no URLs found
            if not urls:
                thumb = await fetch_wikimedia_image(place_name, city)
                return [thumb] if thumb else []

            return urls[:max_images]

    except Exception as e:
        print(f"⚠️ Wikimedia multi-image failed for '{place_name}': {e}")
        # ✅ Always try single thumbnail as last resort
        try:
            thumb = await fetch_wikimedia_image(place_name, city)
            return [thumb] if thumb else []
        except Exception:
            return []


# ============================================================
# WIKIPEDIA — description
# ============================================================
async def fetch_wikipedia_description(place_name: str, city: str) -> str:
    headers = {
        "User-Agent": "GoViaApp/1.0 (travel app; contact@govia.app) httpx/0.24",
        "Accept": "application/json",
    }
    # ✅ Titles to reject — generic city/region articles
    REJECT_TITLES = [
        city.lower(), "india", "maharashtra", "list of",
        "district", "state", "country", "region", "municipality"
    ]
    try:
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": f"{place_name} {city}",
                    "format": "json",
                    "srlimit": 5,
                },
            )
            if not resp.text.strip():
                return f"{place_name} is a notable place in {city}."

            results = resp.json().get("query", {}).get("search", [])
            if not results:
                return f"{place_name} is a notable place in {city}."

            # ✅ Find best match: title contains place name words, not a generic article
            page_title = None
            place_words = [w for w in place_name.lower().split() if len(w) > 3]

            for r in results:
                title_lower = r["title"].lower()
                if any(reject == title_lower for reject in REJECT_TITLES):
                    continue
                if place_words and not any(w in title_lower for w in place_words):
                    continue
                page_title = r["title"]
                break

            # ✅ No relevant article found — return generic, never show wrong city info
            if not page_title:
                print(f"⚠️ No relevant Wikipedia article for '{place_name}'")
                return f"{place_name} is a notable place in {city}, India."

            print(f"📖 Wikipedia: '{place_name}' → '{page_title}'")

            extract_resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "titles": page_title,
                    "prop": "extracts",
                    "exintro": True,
                    "explaintext": True,
                    "exsectionformat": "plain",
                    "format": "json",
                },
            )
            if not extract_resp.text.strip():
                return f"{place_name} is a notable place in {city}."

            pages = extract_resp.json().get("query", {}).get("pages", {})
            for page in pages.values():
                extract = page.get("extract", "").strip()
                if not extract:
                    continue
                # ✅ Sanity check — reject if extract is about the city not the place
                first_200 = extract[:200].lower()
                if (city.lower() in first_200[:40]
                        and place_name.lower() not in first_200):
                    print(f"⚠️ Wrong article for '{place_name}' — using generic")
                    return f"{place_name} is a notable place in {city}, India."
                return extract[:400] + ("..." if len(extract) > 400 else "")

        return f"{place_name} is a notable place in {city}."

    except Exception as e:
        print(f"⚠️ Wikipedia description failed for '{place_name}': {e}")
        return f"{place_name} is a notable place in {city}."


# ============================================================
# OSM — nearby transport (bus stops + metro within 500m)
# ============================================================
async def fetch_nearby_transport(lat: float, lon: float) -> list[dict]:
    headers = {
        "User-Agent": "GoViaApp/1.0 (travel app; contact@govia.app) httpx/0.24",
    }
    try:
        query = f"""
        [out:json][timeout:15];
        (
          node["highway"="bus_stop"](around:500,{lat},{lon});
          node["railway"="station"](around:800,{lat},{lon});
          node["railway"="subway_entrance"](around:500,{lat},{lon});
        );
        out 5;
        """
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            resp = await client.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": query},
            )
        if not resp.text.strip():
            return []
        elements = resp.json().get("elements", [])
        transport = []
        seen_names = set()
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name") or tags.get("name:en")
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            kind = "Metro" if tags.get("railway") else "Bus Stop"
            transport.append({"name": name, "meta": kind})
            if len(transport) >= 5:
                break
        return transport
    except Exception as e:
        print(f"⚠️ Nearby transport failed: {e}")
        return []


# ============================================================
# OSM — nearby hotels (within 1km)
# ============================================================
async def fetch_nearby_hotels(lat: float, lon: float) -> list[dict]:
    headers = {
        "User-Agent": "GoViaApp/1.0 (travel app; contact@govia.app) httpx/0.24",
    }
    try:
        query = f"""
        [out:json][timeout:15];
        (
          node["tourism"="hotel"](around:1500,{lat},{lon});
          node["tourism"="guest_house"](around:1500,{lat},{lon});
          node["tourism"="hostel"](around:1500,{lat},{lon});
          node["tourism"="motel"](around:1500,{lat},{lon});
          node["building"="hotel"](around:1500,{lat},{lon});
        );
        out 8;
        """
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            resp = await client.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": query},
            )
        if not resp.text.strip():
            return []
        elements = resp.json().get("elements", [])
        hotels = []
        seen = set()
        for el in elements[:8]:
            tags = el.get("tags", {})
            name = tags.get("name") or tags.get("name:en")
            if not name or name in seen:
                continue
            seen.add(name)
            stars = tags.get("stars", "")
            tourism_type = tags.get("tourism", "hotel")
            # price estimate based on stars/type
            if stars in ["4", "5"]:
                price = "₹₹₹₹"
            elif stars in ["3"]:
                price = "₹₹₹"
            elif tourism_type in ["hostel"]:
                price = "₹"
            else:
                price = "₹₹"
            # accommodation type label
            type_label = {
                "hotel": "Hotel",
                "guest_house": "Guest House",
                "hostel": "Hostel",
                "motel": "Motel",
            }.get(tourism_type, "Hotel")
            h_lat = el.get("lat")
            h_lon = el.get("lon")
            phone = tags.get("phone", "")
            website = tags.get("website", "")
            hotels.append({
                "name": name,
                "type": type_label,
                "price": price,
                "stars": stars,
                "phone": phone,
                "website": website,
                "lat": h_lat,
                "lon": h_lon,
                "meta": f"{type_label} • {price}",
            })
        return hotels
    except Exception as e:
        print(f"⚠️ Nearby hotels failed: {e}")
        return []


# ============================================================
# OSM HELPERS
# ============================================================
def build_overpass_query(bbox: tuple, category: str) -> str:
    south, west, north, east = bbox
    tag_filter = CATEGORY_QUERIES.get(category, '[tourism="attraction"]')
    return f"""
    [out:json][timeout:25];
    (
      node{tag_filter}({south},{west},{north},{east});
      way{tag_filter}({south},{west},{north},{east});
    );
    out center 20;
    """


def parse_overpass_results(elements: list, category: str, city: str) -> list:
    places = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:en")
        if not name:
            continue
        if el["type"] == "node":
            g_lat, g_lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center", {})
            g_lat, g_lon = center.get("lat"), center.get("lon")
        if not g_lat or not g_lon:
            continue
        places.append({
            "name": name,
            "category": category,
            "city": city.title(),
            "lat": g_lat,
            "lon": g_lon,
            "address": tags.get("addr:street", ""),
            "opening_hours": tags.get("opening_hours", ""),
            "phone": tags.get("phone", tags.get("contact:phone", "")),
            "website": tags.get("website", tags.get("contact:website", "")),
            "rating": None,
            "image_url": None,
            "osm_id": el.get("id"),
        })
    return places


async def fetch_places_from_osm(city: str, category: str) -> list:
    headers = {
        "User-Agent": "GoViaApp/1.0 (travel app; contact@govia.app) httpx/0.24",
    }
    bbox = CITY_BBOX.get(city.lower())
    if not bbox:
        raise HTTPException(status_code=400, detail=f"City '{city}' not supported.")
    query = build_overpass_query(bbox, category)
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        resp = await client.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="OpenStreetMap fetch failed")
    if not resp.text.strip():
        raise HTTPException(status_code=502, detail="OpenStreetMap returned empty response")
    return parse_overpass_results(resp.json().get("elements", []), category, city)


async def enrich_with_images(places: list, city: str) -> list:
    async def fetch_one(place):
        place["image_url"] = await fetch_wikimedia_image(place["name"], city)
        return place
    return list(await asyncio.gather(*[fetch_one(p) for p in places]))


# ============================================================
# ROUTES
# ============================================================

@router.get("/popular")
async def get_popular_places(city: str = Query(default="mumbai")):
    city_key = city.lower()
    cache_key = f"popular_{city_key}"
    cached = places_collection.find_one({"cache_key": cache_key})
    if cached:
        if datetime.utcnow() - cached["cached_at"] < timedelta(hours=24):
            return {"city": city.title(), "places": cached["places"]}

    try:
        places = await fetch_places_from_osm(city_key, "Sights")
        top = await enrich_with_images(places[:6], city_key)
        places_collection.update_one(
            {"cache_key": cache_key},
            {"$set": {"cache_key": cache_key, "city": city.title(),
                      "places": top, "cached_at": datetime.utcnow()}},
            upsert=True,
        )
        return {"city": city.title(), "places": top}
    except Exception as e:
        # ✅ Fallback to stale cache rather than 502
        if cached:
            print(f"⚠️ OSM failed, returning stale cache: {e}")
            return {"city": city.title(), "places": cached["places"]}
        raise HTTPException(status_code=503, detail="OpenStreetMap fetch failed")


@router.get("/nearby")
async def get_nearby_places(city: str = Query(default="mumbai")):
    city_key = city.lower()
    cache_key = f"nearby_{city_key}"
    cached = places_collection.find_one({"cache_key": cache_key})
    if cached:
        if datetime.utcnow() - cached["cached_at"] < timedelta(hours=24):
            return {"city": city.title(), "places": cached["places"]}

    try:
        cafes = await fetch_places_from_osm(city_key, "Cafés")
        food = await fetch_places_from_osm(city_key, "Food")
        nearby = await enrich_with_images((cafes[:2] + food[:2])[:4], city_key)
        places_collection.update_one(
            {"cache_key": cache_key},
            {"$set": {"cache_key": cache_key, "city": city.title(),
                      "places": nearby, "cached_at": datetime.utcnow()}},
            upsert=True,
        )
        return {"city": city.title(), "places": nearby}
    except Exception as e:
        if cached:
            print(f"⚠️ OSM failed, returning stale cache: {e}")
            return {"city": city.title(), "places": cached["places"]}
        raise HTTPException(status_code=503, detail="OpenStreetMap fetch failed")


# ============================================================
# FULL DETAILS — called when user taps a place card
# ============================================================
@router.get("/details")
async def get_place_details(
    city: str = Query(default="mumbai"),
    name: str = Query(...),
    category: str = Query(default="Sights"),
):
    city_key = city.lower()
    details_cache_key = f"details_{city_key}_{name.lower().replace(' ', '_')}"

    # ✅ Return cached details if fresh (6 hours)
    cached = places_collection.find_one({"cache_key": details_cache_key})
    if cached:
        if datetime.utcnow() - cached["cached_at"] < timedelta(hours=6):
            print(f"✅ Returning cached details for '{name}'")
            return cached["details"]

    # ── Find base place data ─────────────────────────────────────────────
    place = None

    # Check popular cache
    pop_cache = places_collection.find_one({"cache_key": f"popular_{city_key}"})
    if pop_cache:
        for p in pop_cache.get("places", []):
            if p["name"].lower() == name.lower():
                place = p
                break

    # Check nearby cache
    if not place:
        near_cache = places_collection.find_one({"cache_key": f"nearby_{city_key}"})
        if near_cache:
            for p in near_cache.get("places", []):
                if p["name"].lower() == name.lower():
                    place = p
                    break

    # ── Check gems cache ──
    if not place:
        gems_cache = places_collection.find_one({"cache_key": f"gems_{city_key}"})
        if gems_cache:
            for g in gems_cache.get("gems", []):
                if g["name"].lower() == name.lower():
                    place = g
                    break

    # ── Try category-based OSM fetch ──
    if not place:
        try:
            places = await fetch_places_from_osm(city_key, category)
            for p in places:
                if p["name"].lower() == name.lower():
                    place = p
                    break
        except Exception:
            pass

    # ── Last resort: direct OSM name search (handles hotels, hostels, etc.) ──
    if not place:
        bbox = CITY_BBOX.get(city_key)
        if bbox:
            south, west, north, east = bbox
            osm_headers = {"User-Agent": "GoViaApp/1.0 (travel app; contact@govia.app)"}
            try:
                query = f"""
[out:json][timeout:20];
(
  node["name"~"{name}",i]({south},{west},{north},{east});
  way["name"~"{name}",i]({south},{west},{north},{east});
);
out center 5;
"""
                async with httpx.AsyncClient(timeout=20, headers=osm_headers) as client:
                    resp = await client.post(
                        "https://overpass-api.de/api/interpreter",
                        data={"data": query},
                    )
                if resp.text.strip():
                    elements = resp.json().get("elements", [])
                    for el in elements:
                        tags = el.get("tags", {})
                        el_name = tags.get("name") or tags.get("name:en", "")
                        if el_name.lower() == name.lower():
                            if el["type"] == "node":
                                lat_v, lon_v = el.get("lat"), el.get("lon")
                            else:
                                c = el.get("center", {})
                                lat_v, lon_v = c.get("lat"), c.get("lon")
                            place = {
                                "name": el_name,
                                "category": category,
                                "city": city.title(),
                                "lat": lat_v or 0,
                                "lon": lon_v or 0,
                                "address": tags.get("addr:street", ""),
                                "opening_hours": tags.get("opening_hours", ""),
                                "phone": tags.get("phone", tags.get("contact:phone", "")),
                                "website": tags.get("website", tags.get("contact:website", "")),
                            }
                            print(f"✅ Found '{name}' via direct OSM name search")
                            break
            except Exception as e:
                print(f"⚠️ Direct OSM search failed for '{name}': {e}")

    # ── If still not found, build minimal place from name + city ──
    # (allows Wikipedia/Wikimedia to still fetch description and images)
    if not place:
        print(f"⚠️ '{name}' not found in OSM, building minimal place")
        place = {
            "name": name,
            "category": category,
            "city": city.title(),
            "lat": 0,
            "lon": 0,
            "address": "",
            "opening_hours": "",
            "phone": "",
            "website": "",
        }

    lat = place.get("lat", 0)
    lon = place.get("lon", 0)

    print(f"🔍 Fetching full details for '{name}' ({city})...")

    # ── Fetch FSQ data + transport + hotels concurrently ─────────────────
    fsq_data, transport, hotels = await asyncio.gather(
        fetch_fsq_place_data(name, lat, lon, city_key),
        fetch_nearby_transport(lat, lon),
        fetch_nearby_hotels(lat, lon),
    )

    # ── Use FSQ data, fall back to Wikipedia for description/images ───────
    description = fsq_data.get("description", "")
    images = fsq_data.get("images", [])
    phone = fsq_data.get("phone") or place.get("phone", "")
    website = fsq_data.get("website") or place.get("website", "")
    opening_hours = fsq_data.get("hours") or place.get("opening_hours", "")

    # ✅ No FSQ description — use safe generic, never pull wrong Wikipedia article
    if not description:
        description = f"{name} is a notable place in {city.title()}, India."

    # ✅ No FSQ images — try strict Wikipedia thumbnail for sights
    if not images:
        wiki_img = await fetch_strict_wikipedia_image(name, city_key)
        if wiki_img:
            images = [wiki_img]

    details = {
        "name": place["name"],
        "category": place.get("category", category),
        "city": place.get("city", city.title()),
        "lat": lat,
        "lon": lon,
        "address": place.get("address", ""),
        "opening_hours": opening_hours,
        "phone": phone,
        "website": website,
        "description": description,
        "images": images,
        "nearby_transport": transport,
        "nearby_hotels": hotels,
    }

    # ✅ Cache details for 6 hours
    places_collection.update_one(
        {"cache_key": details_cache_key},
        {"$set": {
            "cache_key": details_cache_key,
            "details": details,
            "cached_at": datetime.utcnow(),
        }},
        upsert=True,
    )

    print(f"✅ Details ready for '{name}': {len(images)} images, "
          f"{len(transport)} transport, {len(hotels)} hotels")

    return details


# ============================================================
# GET /places/hidden-gems?city=mumbai
# ── Fetches lesser-known places from OSM not in popular list
# ============================================================
@router.get("/hidden-gems")
async def get_hidden_gems(
    city: str = Query(default="mumbai"),
    lat: float = Query(default=None),
    lon: float = Query(default=None),
    radius_km: float = Query(default=10.0),
):
    city_key = city.lower()
    cache_key = f"gems_{city_key}"

    # ✅ Cache for 12 hours
    cached = places_collection.find_one({"cache_key": cache_key})
    if cached:
        if datetime.utcnow() - cached["cached_at"] < timedelta(hours=12):
            all_gems = cached["gems"]
            # ✅ If lat/lon provided, filter cached gems by proximity
            if lat is not None and lon is not None:
                filtered = [
                    g for g in all_gems
                    if g.get("lat") and g.get("lon") and
                    haversine(lat, lon, g["lat"], g["lon"]) <= radius_km
                ]
                filtered.sort(key=lambda g: haversine(lat, lon, g["lat"], g["lon"]))
                return {"city": city.title(), "gems": filtered[:10]}
            return {"city": city.title(), "gems": all_gems}

    bbox = CITY_BBOX.get(city_key)
    if not bbox:
        raise HTTPException(status_code=400, detail=f"City '{city}' not supported.")

    south, west, north, east = bbox
    bbox_str = f"{south},{west},{north},{east}"

    # ✅ Build union query for all gem tag types
    node_ways = "\n".join([
        f'  node{tag}({bbox_str});\n  way{tag}({bbox_str});'
        for tag in GEM_TAGS
    ])
    query = f"[out:json][timeout:25];\n(\n{node_ways}\n);\nout center 40;"

    print(f"💎 Fetching hidden gems for {city}...")

    osm_headers = {
        "User-Agent": "GoViaApp/1.0 (travel app; contact@govia.app) httpx/0.24",
    }
    try:
        async with httpx.AsyncClient(timeout=55, headers=osm_headers) as client:
            resp = await client.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": query},
            )
        if not resp.text.strip():
            raise ValueError("OSM returned empty response")
        elements = resp.json().get("elements", [])
    except Exception as e:
        print(f"⚠️ OSM gems fetch failed: {e}")
        # ✅ Fallback to stale cache rather than 503
        if cached:
            print("♻️ Returning stale gems cache")
            all_gems = cached["gems"]
            if lat is not None and lon is not None:
                filtered = [
                    g for g in all_gems
                    if g.get("lat") and g.get("lon") and
                    haversine(lat, lon, g["lat"], g["lon"]) <= radius_km
                ]
                filtered.sort(key=lambda g: haversine(lat, lon, g["lat"], g["lon"]))
                return {"city": city.title(), "gems": filtered[:10]}
            return {"city": city.title(), "gems": all_gems[:10]}
        # ✅ No cache at all — return empty instead of 503 so app doesn't crash
        print(f"⚠️ No gems cache and OSM failed — returning empty")
        return {"city": city.title(), "gems": []}

    # ✅ Get popular place names to exclude them
    pop_cache = places_collection.find_one({"cache_key": f"popular_{city_key}"})
    popular_names = set()
    if pop_cache:
        popular_names = {p["name"].lower() for p in pop_cache.get("places", [])}

    gems = []
    seen_names = set()

    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:en")
        if not name or name.lower() in popular_names or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())

        if el["type"] == "node":
            g_lat, g_lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center", {})
            g_lat, g_lon = center.get("lat"), center.get("lon")

        if not g_lat or not g_lon:
            continue

        gems.append({
            "name": name,
            "vibe": gem_vibe(tags),
            "category": (
                tags.get("tourism") or tags.get("historic") or
                tags.get("natural") or tags.get("leisure") or
                tags.get("amenity") or "hidden"
            ).replace("_", " ").title(),
            "city": city.title(),
            "lat": g_lat,
            "lon": g_lon,
            "address": tags.get("addr:street", ""),
            "opening_hours": tags.get("opening_hours", ""),
            "phone": tags.get("phone", ""),
            "website": tags.get("website", ""),
            "image_url": None,
        })

        if len(gems) >= 30:  # fetch more, then filter
            break

    # ✅ Filter by proximity if lat/lon provided
    if lat is not None and lon is not None:
        gems = [
            g for g in gems
            if haversine(lat, lon, g["lat"], g["lon"]) <= radius_km
        ]
        # sort by distance
        gems.sort(key=lambda g: haversine(lat, lon, g["lat"], g["lon"]))

    gems = gems[:10]  # cap at 10

    # ✅ Fetch images concurrently
    async def fetch_gem_image(gem):
        gem["image_url"] = await fetch_wikimedia_image(gem["name"], city_key)
        return gem

    gems = list(await asyncio.gather(*[fetch_gem_image(g) for g in gems]))

    places_collection.update_one(
        {"cache_key": cache_key},
        {"$set": {
            "cache_key": cache_key,
            "city": city.title(),
            "gems": gems,
            "cached_at": datetime.utcnow(),
        }},
        upsert=True,
    )

    print(f"✅ Found {len(gems)} hidden gems for {city}")
    return {"city": city.title(), "gems": gems}


# ============================================================
# GET /places/gem-details?city=mumbai&name=...
# ── Full details for a hidden gem
# ============================================================
@router.get("/gem-details")
async def get_gem_details(
    city: str = Query(default="mumbai"),
    name: str = Query(...),
):
    city_key = city.lower()
    cache_key = f"gem_details_{city_key}_{name.lower().replace(' ', '_')}"

    # ✅ Cache for 6 hours
    cached = places_collection.find_one({"cache_key": cache_key})
    if cached:
        if datetime.utcnow() - cached["cached_at"] < timedelta(hours=6):
            return cached["details"]

    # ── Find base gem data from gems cache ──
    gem = None
    gems_cache = places_collection.find_one({"cache_key": f"gems_{city_key}"})
    if gems_cache:
        for g in gems_cache.get("gems", []):
            if g["name"].lower() == name.lower():
                gem = g
                break

    if not gem:
        raise HTTPException(status_code=404, detail=f"Gem '{name}' not found")

    lat = gem.get("lat", 0)
    lon = gem.get("lon", 0)

    print(f"💎 Fetching gem details for '{name}'...")

    # ✅ Fetch FSQ + transport concurrently
    fsq_data, transport = await asyncio.gather(
        fetch_fsq_place_data(name, lat, lon, city_key),
        fetch_nearby_transport(lat, lon),
    )

    description = fsq_data.get("description", "")
    images = fsq_data.get("images", [])
    phone = fsq_data.get("phone") or gem.get("phone", "")
    website = fsq_data.get("website") or gem.get("website", "")
    opening_hours = fsq_data.get("hours") or gem.get("opening_hours", "")

    # ✅ No FSQ description — use safe generic
    if not description:
        description = f"{name} is a hidden gem in {city.title()}, India."
    # ✅ No FSQ images — try strict Wikipedia thumbnail
    if not images:
        wiki_img = await fetch_strict_wikipedia_image(name, city_key)
        if wiki_img:
            images = [wiki_img]

    details = {
        "name": gem["name"],
        "vibe": gem.get("vibe", "Off The Map"),
        "category": gem.get("category", "Hidden"),
        "city": gem.get("city", city.title()),
        "lat": lat,
        "lon": lon,
        "address": gem.get("address", ""),
        "opening_hours": opening_hours,
        "phone": phone,
        "website": website,
        "description": description,
        "images": images,
        "nearby_transport": transport,
    }

    places_collection.update_one(
        {"cache_key": cache_key},
        {"$set": {
            "cache_key": cache_key,
            "details": details,
            "cached_at": datetime.utcnow(),
        }},
        upsert=True,
    )

    return details