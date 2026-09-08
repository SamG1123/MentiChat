from flask_login import UserMixin
import json
import os
import secrets
from werkzeug.security import generate_password_hash, check_password_hash


class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# Simple file-based user storage
USERS_FILE = 'users.json'


def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r') as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)


def get_user_by_username(username):
    users = load_users()
    user_data = users.get(username)
    if user_data:
        return User(id=user_data['id'], username=user_data['username'],
                    password_hash=user_data['password_hash'])
    return None


def get_user_by_id(user_id):
    users = load_users()
    for username, user_data in users.items():
        if user_data['id'] == user_id:
            return User(id=user_data['id'], username=user_data['username'],
                        password_hash=user_data['password_hash'])
    return None


def create_user(username, password):
    users = load_users()
    if username in users:
        return None
    # Generate a simple ID (in production, use UUID or database auto-increment)
    user_id = str(len(users) + 1)
    # Hash the password properly
    password_hash = generate_password_hash(password)
    users[username] = {
        'id': user_id,
        'username': username,
        'password_hash': password_hash
    }
    save_users(users)
    return User(id=user_id, username=username, password_hash=password_hash)