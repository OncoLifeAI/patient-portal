"""
Authentication Routes

This module provides authentication endpoints using AWS Cognito:

Routes:
- POST /auth/signup: Register a new user account
- POST /auth/login: Authenticate user and get tokens
- POST /auth/complete-new-password: Complete new password challenge for first-time users

All routes handle Cognito integration and manage user data in the patient database.
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
import boto3
from botocore.exceptions import ClientError
import logging
import hmac
import hashlib
import base64
from routers.auth.models import (
    SignupRequest,
    SignupResponse,
    LoginRequest,
    LoginResponse,
    CompleteNewPasswordRequest,
    CompleteNewPasswordResponse,
    AuthTokens,
)
# Import DB session and models
from database import get_patient_db
from routers.db.models import PatientInfo, PatientConfigurations


# Load environment variables
load_dotenv()

# Create router
router = APIRouter(prefix="/auth", tags=["authentication"])

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_cognito_client():
    """Get AWS Cognito client"""
    return boto3.client(
        "cognito-idp",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def _get_secret_hash(username: str, client_id: str, client_secret: str) -> str:
    """Calculates the SecretHash for Cognito API calls."""
    msg = username + client_id
    dig = hmac.new(
        key=client_secret.encode("utf-8"),
        msg=msg.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(dig).decode()


@router.post("/signup", response_model=SignupResponse)
async def signup_user(request: SignupRequest, db: Session = Depends(get_patient_db)):
    """
    Create a new user in AWS Cognito User Pool.
    On success, also creates corresponding records in the patient_info
    and patient_configurations tables.
    """
    try:
        user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
        if not user_pool_id:
            raise HTTPException(
                status_code=500, detail="COGNITO_USER_POOL_ID not configured"
            )

        cognito_client = get_cognito_client()

        user_attributes = [
            {"Name": "email", "Value": request.email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "given_name", "Value": request.first_name},
            {"Name": "family_name", "Value": request.last_name},
        ]

        response = cognito_client.admin_create_user(
            UserPoolId=user_pool_id,
            Username=request.email,
            UserAttributes=user_attributes,
            ForceAliasCreation=False,
        )

        # Extract the UUID (sub) that Cognito automatically generates
        user_sub = None
        for attribute in response["User"]["Attributes"]:
            if attribute["Name"] == "sub":
                user_sub = attribute["Value"]
                break
        
        if not user_sub:
            # This is a critical failure, should be investigated if it occurs
            logger.error(f"Could not find UUID in Cognito response for {request.email}")
            raise HTTPException(status_code=500, detail="User created in Cognito, but failed to retrieve UUID.")

        logger.info(
            f"Successfully created user in Cognito: {request.email}. User UUID (sub): {user_sub}"
        )

        # Now, create the corresponding records in our own database
        new_patient_info = PatientInfo(
            uuid=user_sub,
            email_address=request.email,
            first_name=request.first_name,
            last_name=request.last_name,
        )
        new_patient_config = PatientConfigurations(uuid=user_sub)

        db.add(new_patient_info)
        db.add(new_patient_config)
        db.commit()
        
        logger.info(f"Successfully created database records for user {user_sub}")

        return SignupResponse(
            message=f"User {request.email} created successfully. A temporary password has been sent to their email.",
            email=request.email,
            user_status=response["User"]["UserStatus"],
        )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]

        if error_code == "UsernameExistsException":
            raise HTTPException(
                status_code=400, detail=f"User with email {request.email} already exists"
            )
        else:
            logger.error(f"Cognito error: {error_code} - {error_message}")
            raise HTTPException(
                status_code=500, detail=f"AWS Cognito error: {error_message}"
            )

    except Exception as e:
        logger.error(f"Unexpected error creating user: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/login", response_model=LoginResponse)
async def validate_login(request: LoginRequest):
    """
    Validate if a user's email and password is valid for login.
    If a temporary password is used, it returns a session token for the password change flow.
    """
    try:
        user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
        client_id = os.getenv("COGNITO_CLIENT_ID")
        client_secret = os.getenv("COGNITO_CLIENT_SECRET")

        if not user_pool_id or not client_id:
            logger.error("Cognito environment variables not configured.")
            raise HTTPException(
                status_code=500,
                detail="COGNITO_USER_POOL_ID or COGNITO_CLIENT_ID not configured",
            )

        cognito_client = get_cognito_client()

        auth_parameters = {"USERNAME": request.email, "PASSWORD": request.password}

        if client_secret:
            auth_parameters["SECRET_HASH"] = _get_secret_hash(
                request.email, client_id, client_secret
            )

        auth_response = cognito_client.admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters=auth_parameters,
        )

        logger.info(f"Cognito auth response for {request.email}: {auth_response}")

        if "AuthenticationResult" in auth_response:
            logger.info(f"Successful login for: {request.email}")
            auth_result = auth_response["AuthenticationResult"]
            tokens = AuthTokens(
                access_token=auth_result["AccessToken"],
                refresh_token=auth_result["RefreshToken"],
                id_token=auth_result["IdToken"],
                token_type=auth_result["TokenType"],
            )
            return LoginResponse(
                valid=True,
                message="Login credentials are valid",
                user_status="CONFIRMED",
                tokens=tokens
            )

        elif "ChallengeName" in auth_response:
            challenge_name = auth_response["ChallengeName"]
            session = auth_response.get("Session")
            logger.info(
                f"Login for {request.email} requires challenge: {challenge_name}"
            )

            if challenge_name == "NEW_PASSWORD_REQUIRED":
                return LoginResponse(
                    valid=True,
                    message="Login credentials are valid but password change is required.",
                    user_status="FORCE_CHANGE_PASSWORD",
                    session=session,
                )
            else:
                return LoginResponse(
                    valid=True,
                    message=f"Login credentials are valid but challenge required: {challenge_name}",
                    user_status="CHALLENGE_REQUIRED",
                    session=session,
                )
        else:
            logger.warning(f"Unexpected Cognito response for {request.email}: {auth_response}")
            return LoginResponse(valid=False, message="Unexpected authentication response")

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        logger.error(f"Cognito ClientError for {request.email}: Code={error_code}, Message='{error_message}'")

        if error_code == "NotAuthorizedException":
            logger.info(f"Invalid login attempt for: {request.email} (NotAuthorizedException)")
            return LoginResponse(valid=False, message="Invalid email or password")
        elif error_code == "UserNotFoundException":
            logger.info(f"User not found: {request.email}")
            return LoginResponse(valid=False, message="User not found")
        else:
            logger.error(
                f"Unhandled Cognito error during login validation: {error_code} - {error_message}"
            )
            raise HTTPException(
                status_code=500, detail=f"AWS Cognito error: {error_message}"
            )

    except Exception as e:
        logger.error(f"Unexpected server error during login validation for {request.email}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/complete-new-password", response_model=CompleteNewPasswordResponse)
async def complete_new_password(request: CompleteNewPasswordRequest):
    """
    Complete the new password setup for a user who was created with a temporary password.
    """
    try:
        user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
        client_id = os.getenv("COGNITO_CLIENT_ID")
        client_secret = os.getenv("COGNITO_CLIENT_SECRET")

        if not user_pool_id or not client_id:
            raise HTTPException(
                status_code=500,
                detail="COGNITO_USER_POOL_ID or COGNITO_CLIENT_ID not configured",
            )

        cognito_client = get_cognito_client()

        challenge_responses = {
            "USERNAME": request.email,
            "NEW_PASSWORD": request.new_password,
        }

        if client_secret:
            challenge_responses["SECRET_HASH"] = _get_secret_hash(
                request.email, client_id, client_secret
            )

        response = cognito_client.admin_respond_to_auth_challenge(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            ChallengeName="NEW_PASSWORD_REQUIRED",
            Session=request.session,
            ChallengeResponses=challenge_responses,
        )

        if "AuthenticationResult" in response:
            auth_result = response["AuthenticationResult"]
            tokens = AuthTokens(
                access_token=auth_result["AccessToken"],
                refresh_token=auth_result["RefreshToken"],
                id_token=auth_result["IdToken"],
                token_type=auth_result["TokenType"],
            )
            logger.info(
                f"Successfully set new password and authenticated user: {request.email}"
            )
            return CompleteNewPasswordResponse(
                message="Password successfully changed and user authenticated.",
                tokens=tokens,
            )
        else:
            logger.error(
                f"Unexpected response from Cognito for {request.email} while setting new password: {response}"
            )
            raise HTTPException(
                status_code=400,
                detail="Could not set new password. Unexpected response from authentication service.",
            )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        logger.error(
            f"Cognito error setting new password for {request.email}: {error_code} - {error_message}"
        )
        if error_code in [
            "NotAuthorizedException",
            "CodeMismatchException",
            "ExpiredCodeException",
        ]:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired session. Please try logging in again.",
            )
        if error_code == "InvalidPasswordException":
            raise HTTPException(
                status_code=400,
                detail=f"New password does not meet requirements: {error_message}",
            )
        raise HTTPException(
            status_code=500, detail=f"AWS Cognito error: {error_message}"
        )

    except Exception as e:
        logger.error(
            f"Unexpected error setting new password for {request.email}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")