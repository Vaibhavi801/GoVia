from bson import ObjectId
from db.connection import db

users = db["users"]

def find_user(email: str):
    return users.find_one({"email": email})

def find_user_by_id(user_id: str):
    return users.find_one({"_id": ObjectId(user_id)})

def create_user(user_doc: dict):
    return users.insert_one(user_doc)
