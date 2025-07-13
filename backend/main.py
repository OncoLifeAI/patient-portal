from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn
import os

# Import routers
from routers.auth.auth_routes import router as auth_router
from routers.db.db_routes import router as db_router

# Load environment variables
load_dotenv()

# Create main FastAPI application
app = FastAPI(
    title="Patient Portal API",
    description="API for the Patient Portal application",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(db_router)

# Root endpoint
@app.get("/")
async def root():
    return {"message": "Welcome to Patient Portal API", "version": "1.0.0"}

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        reload_dirs=["./"]
    )