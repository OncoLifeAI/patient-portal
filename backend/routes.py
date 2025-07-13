from fastapi import FastAPI, Depends
from pydantic import BaseModel
from typing import List

app = FastAPI()

class Conversation(BaseModel):
    id: int
    message: str
    timestamp: str
