from fastapi import FastAPI, Depends
from .auth import validate_token
from .users import get_user

app = FastAPI()


def session_dep():
    return {"session": True}


@app.on_event("startup")
async def on_startup():
    return None


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/users")
async def create_user(token=Depends(validate_token), session=Depends(session_dep)):
    user = get_user(1)
    return user


@app.get("/users/{user_id}")
async def read_user(user_id: int, token=Depends(validate_token)):
    return get_user(user_id)
