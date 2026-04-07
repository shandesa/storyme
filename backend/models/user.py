"""User data model."""

from pydantic import BaseModel
from datetime import datetime, timezone


class User(BaseModel):
    mobile: str
    password: str
    country_code: str = "+91"
    created_at: datetime = None

    def model_post_init(self, __context):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
