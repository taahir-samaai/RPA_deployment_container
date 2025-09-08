"""
RPA Orchestration System - Authentication Utilities
--------------------------------------------------
Authentication and authorization utilities for the RPA orchestration system.
"""
import datetime
import logging
from typing import Optional, Dict, Any, Union

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from config import Config
import db

logger = logging.getLogger(__name__)

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Models
class User(BaseModel):
    username: str
    disabled: bool = False

class UserInDB(User):
    id: int
    hashed_password: str
    created_at: datetime.datetime
    last_login: Optional[datetime.datetime] = None

class TokenData(BaseModel):
    username: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify password against hashed version.
    
    Args:
        plain_password: Plain text password
        hashed_password: Hashed password from database
        
    Returns:
        bool: True if password matches, False otherwise
    """
    try:
        # Handle different password hash formats
        if hashed_password.startswith('$2'):
            # bcrypt format
            return bcrypt.checkpw(
                plain_password.encode('utf-8'), 
                hashed_password.encode('utf-8')
            )
        else:
            # Legacy format or invalid format
            logger.warning("Invalid password hash format detected")
            return False
    except Exception as e:
        logger.error(f"Error verifying password: {str(e)}")
        return False

def get_password_hash(password: str) -> str:
    """
    Generate password hash.
    
    Args:
        password: Plain text password
        
    Returns:
        str: Hashed password
    """
    try:
        # Use a higher work factor for better security (12 is good as of 2023)
        return bcrypt.hashpw(
            password.encode('utf-8'), 
            bcrypt.gensalt(rounds=12)
        ).decode('utf-8')
    except Exception as e:
        logger.error(f"Error generating password hash: {str(e)}")
        raise

def get_user(username: str) -> Optional[UserInDB]:
    """
    Get a user from the database by username.
    
    Args:
        username: Username to look up
        
    Returns:
        UserInDB: User object if found, None otherwise
    """
    user_dict = db.get_user_by_username(username)
    if user_dict:
        return UserInDB(**user_dict)
    return None

def authenticate_user(username: str, password: str) -> Union[UserInDB, bool]:
    """
    Authenticate a user.
    
    Args:
        username: Username
        password: Plain text password
        
    Returns:
        UserInDB: User object if authentication successful, False otherwise
    """
    user = get_user(username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def check_permission(permission: str):
    """
    Minimal permission checker that always allows access.
    Returns a dependency function for FastAPI.
    
    Args:
        permission: Permission string (e.g., "job:create")
        
    Returns:
        Dependency function that returns permission info
    """
    def permission_dependency():
        # For now, always allow access with minimal info
        return {
            "permission": permission,
            "allowed": True,
            "source": "minimal_auth"
        }
    
    return permission_dependency

def create_access_token(data: Dict[str, Any], expires_delta: Optional[datetime.timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Data to encode in the token
        expires_delta: Optional expiration time delta
        
    Returns:
        str: Encoded JWT token
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=Config.JWT_EXPIRATION_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, Config.JWT_SECRET, algorithm=Config.JWT_ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserInDB:
    """
    Get the current user from JWT token.
    
    Args:
        token: JWT token
        
    Returns:
        UserInDB: Current user
        
    Raises:
        HTTPException: If token is invalid
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, Config.JWT_SECRET, algorithms=[Config.JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except jwt.PyJWTError:
        raise credentials_exception
    user = get_user(token_data.username)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: UserInDB = Depends(get_current_user)) -> UserInDB:
    """
    Ensure the user is active.
    
    Args:
        current_user: Current user
        
    Returns:
        UserInDB: Current active user
        
    Raises:
        HTTPException: If user is disabled
    """
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def login_for_access_token(form_data: OAuth2PasswordRequestForm) -> Dict[str, str]:
    """
    Process a login request and generate access token.
    
    Args:
        form_data: OAuth2 password request form
        
    Returns:
        dict: Access token data
        
    Raises:
        HTTPException: If authentication fails
    """
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = datetime.timedelta(minutes=Config.JWT_EXPIRATION_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, 
        expires_delta=access_token_expires
    )
    
    # Update last login time
    db.update_user_last_login(user.username)
    
    return {"access_token": access_token, "token_type": "bearer"}

def create_default_admin() -> bool:
    """
    Create default admin user if no users exist.
    
    Returns:
        bool: True if admin created or already exists, False on error
    """
    # Check if any users exist
    existing_user = db.get_user_by_username(Config.ADMIN_USERNAME)
    if existing_user:
        logger.info(f"Default admin user already exists: {Config.ADMIN_USERNAME}")
        return True
    
    # Create default admin user
    hashed_password = get_password_hash(Config.ADMIN_PASSWORD)
    user = db.create_user(Config.ADMIN_USERNAME, hashed_password)
    
    if user:
        logger.info(f"Created default admin user: {Config.ADMIN_USERNAME}")
        return True
    
    logger.error(f"Failed to create default admin user")
    return False

