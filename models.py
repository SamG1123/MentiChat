import secrets
from functools import lru_cache

from flask_login import UserMixin
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash, check_password_hash

from config import config


class User(UserMixin):
    def __init__(self, id: str, username: str, password_hash: str):
        self.id = id
        self.username = username
        self.password_hash = password_hash

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class AuthenticationConfigurationError(RuntimeError):
    """Raised when MongoDB authentication storage is not configured."""


@lru_cache(maxsize=1)
def _users_collection() -> Collection:
    if not config.MONGODB_URI:
        raise AuthenticationConfigurationError(
            "Set MONGODB_URI to connect the authentication database."
        )

    client = MongoClient(config.MONGODB_URI)
    collection = client[config.MONGODB_DATABASE]["users_menti"]
    collection.create_index("username_key", unique=True, name="username_key_unique")
    return collection


def get_user_by_username(username: str) -> User | None:
    user_data = _users_collection().find_one({"username_key": username.casefold()})
    if not user_data:
        return None
    return User(
        id=str(user_data["_id"]),
        username=user_data["username"],
        password_hash=user_data["password_hash"],
    )


def get_user_by_id(user_id: str) -> User | None:
    user_data = _users_collection().find_one({"_id": user_id})
    if not user_data:
        return None
    return User(
        id=str(user_data["_id"]),
        username=user_data["username"],
        password_hash=user_data["password_hash"],
    )


def create_user(username: str, password: str) -> User | None:
    user_id = secrets.token_urlsafe(16)
    password_hash = generate_password_hash(password)
    user_document = {
        "_id": user_id,
        "username": username,
        "username_key": username.casefold(),
        "password_hash": password_hash,
    }

    try:
        _users_collection().insert_one(user_document)
    except DuplicateKeyError:
        return None

    return User(id=user_id, username=username, password_hash=password_hash)