from pydantic import BaseModel, Field

class PlaceCreate(BaseModel):
    name: str
    address: str
    latitude: float
    longitude: float
    category: str

class PlaceInDB(PlaceCreate):
    place_hash: str = Field(...)
