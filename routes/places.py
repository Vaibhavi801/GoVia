from fastapi import APIRouter
from pymongo.errors import DuplicateKeyError
from flutter_backend.models.place import PlaceCreate
from flutter_backend.services.place_service import create_place_fingerprint
from db.connection import db

router = APIRouter()

@router.post("/places")
def create_place(place: PlaceCreate):
    place_hash = create_place_fingerprint(
        place.name,
        place.address,
        place.latitude,
        place.longitude
    )

   
    existing = db.places.find_one({"place_hash": place_hash})
    if existing:
        existing["_id"] = str(existing["_id"])
        existing["already_exists"] = True
        return existing

    place_data = place.model_dump()
    place_data["place_hash"] = place_hash

    try:
       
        result = db.places.insert_one(place_data)
        place_data["_id"] = str(result.inserted_id)
        place_data["already_exists"] = False
        return place_data

    except DuplicateKeyError:
        # 3️⃣ Race-condition fallback
        existing = db.places.find_one({"place_hash": place_hash})
        if existing:
            existing["_id"] = str(existing["_id"])
            existing["already_exists"] = True
            return existing

        # Extremely rare edge case
        raise
