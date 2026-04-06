from fastapi import FastAPI
from routes.auth import router as auth_router

app = FastAPI()

# Include Auth Routes
app.include_router(auth_router)

@app.get("/")
def root():
    return {"message": "StoryMe API running"}
