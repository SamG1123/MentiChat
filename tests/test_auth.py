import unittest
from unittest.mock import patch

from pymongo.errors import DuplicateKeyError

from app import app
from models import AuthenticationConfigurationError


class FakeUsersCollection:
    def __init__(self):
        self.documents = {}
        self.documents_by_id = {}

    def find_one(self, query):
        if "_id" in query:
            return self.documents_by_id.get(query["_id"])
        return self.documents.get(query["username_key"])

    def insert_one(self, document):
        key = document["username_key"]
        if key in self.documents:
            raise DuplicateKeyError("username already exists")
        self.documents[key] = document
        self.documents_by_id[document["_id"]] = document


class AuthenticationRoutesTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.users = FakeUsersCollection()
        self.collection_patch = patch("models._users_collection", return_value=self.users)
        self.collection_patch.start()
        self.addCleanup(self.collection_patch.stop)

    def test_register_login_and_logout(self):
        response = self.client.post(
            "/register",
            data={
                "username": "StudyUser",
                "password": "secure-password",
                "confirm_password": "secure-password",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/logout").status_code, 302)

        response = self.client.post(
            "/login",
            data={"username": "studyuser", "password": "secure-password"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_duplicate_username_is_case_insensitive(self):
        self.client.post(
            "/register",
            data={
                "username": "StudyUser",
                "password": "secure-password",
                "confirm_password": "secure-password",
            },
        )
        self.client.post("/logout")
        response = self.client.post(
            "/register",
            data={
                "username": "studyuser",
                "password": "another-password",
                "confirm_password": "another-password",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Username already exists", response.data)

    def test_registration_rejects_short_password(self):
        response = self.client.post(
            "/register",
            data={
                "username": "StudyUser",
                "password": "short",
                "confirm_password": "short",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Password must be at least 8 characters", response.data)

    def test_database_configuration_failure_is_reported(self):
        with patch(
            "models._users_collection",
            side_effect=AuthenticationConfigurationError("MongoDB is not configured"),
        ):
            with self.assertLogs("ncert-tutor", level="ERROR"):
                response = self.client.post(
                    "/login",
                    data={"username": "StudyUser", "password": "secure-password"},
                )

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Account storage is unavailable", response.data)

    def test_reset_requires_login(self):
        response = self.client.post("/api/reset")
        self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
