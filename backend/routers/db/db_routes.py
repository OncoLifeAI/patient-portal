from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
import uuid
from datetime import time

# Use absolute imports from the 'backend' directory
from database import get_patient_db
from routers.db.models import PatientConfigurations # Renamed from PatientLoginInfo
from routers.auth.dependencies import get_current_user, TokenData

# --- Pydantic Schema ---
# This class defines the shape of the data that will be returned in the API response.
# It is updated to match the new PatientConfigurations model.
class PatientConfigurationsSchema(BaseModel):
    uuid: uuid.UUID
    reminder_method: str | None = None
    reminder_time: time | None = None
    acknowledgement_done: bool | None = None
    agreed_conditions: bool | None = None
    is_deleted: bool

    class Config:
        orm_mode = True # Allows Pydantic to read data directly from the ORM model

router = APIRouter(prefix="/db", tags=["database"])

@router.get(
    "/patient-configurations",
    response_model=List[PatientConfigurationsSchema],
    summary="Fetch all patient configuration records",
    description="""
    Retrieves all configuration records from the patient_configurations table. 
    **This is a protected endpoint.** You must provide a valid Cognito
    `access_token` in the `Authorization: Bearer <token>` header.
    """
)
async def get_patient_configurations( # Renamed from get_patient_login_info
    db: Session = Depends(get_patient_db),
    current_user: TokenData = Depends(get_current_user)
):
    """
    - **db**: Injected PATIENT database session.
    - **current_user**: Injected dependency that validates the Cognito token.
      If the token is invalid, this function will never execute.
    """
    print(f"Authenticated user '{current_user.email}' (sub: {current_user.sub}) is accessing patient configurations.")
    
    configs = db.query(PatientConfigurations).all()
        
    return configs 