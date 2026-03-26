import hashlib

def generate_md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()
