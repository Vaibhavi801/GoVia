from flutter_backend.utils.hash_utils import generate_md5

def create_place_fingerprint(name: str, address: str, lat: float, lng: float) -> str:
    raw_string = f"{name.strip().lower()}|{address.strip().lower()}|{lat}|{lng}"
    return generate_md5(raw_string)
