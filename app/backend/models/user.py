from pydantic import BaseModel
from datetime import datetime

class User(BaseModel):
    mobile: str
    password: str
    country_code: str = "+91"
    created_at: datetime = datetime.utcnow()
