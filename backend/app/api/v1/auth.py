from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List
from app.core.database import get_db
from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    encrypt_secret,
    decrypt_secret,
    mask_secret,
)
from app.models.user import User, UserApiKey
from app.schemas.auth import (
    UserRegister,
    UserLogin,
    UserResponse,
    Token,
    ApiKeyCreate,
    ApiKeyResponse,
)
from app.api.deps import get_current_user

router = APIRouter()

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserRegister, db: AsyncSession = Depends(get_db)):
    """Registers a new user account with hashed password and returns access token."""
    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == user_in.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )

    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return Token(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )

@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    """Authenticates email & password, returning JWT access token."""
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    token = create_access_token(user.id)
    return Token(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Returns profile for currently authenticated user."""
    return UserResponse.model_validate(current_user)

# ==============================================================================
# Encrypted API Key Secrets Vault (Fernet AES-256)
# ==============================================================================

@router.post("/secrets", response_model=ApiKeyResponse)
async def store_secret_api_key(
    key_in: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Encrypts and stores a third-party AI provider API key into the user's secret vault.
    Never persists plaintext keys to the database.
    """
    provider_clean = key_in.provider.lower().strip()
    encrypted = encrypt_secret(key_in.api_key.strip())

    # Check if provider key already exists for this user (upsert)
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == current_user.id,
            UserApiKey.provider == provider_clean
        )
    )
    existing_key = result.scalar_one_or_none()

    if existing_key:
        existing_key.encrypted_key = encrypted
        await db.commit()
        await db.refresh(existing_key)
        target = existing_key
    else:
        target = UserApiKey(
            user_id=current_user.id,
            provider=provider_clean,
            encrypted_key=encrypted
        )
        db.add(target)
        await db.commit()
        await db.refresh(target)

    return ApiKeyResponse(
        id=target.id,
        provider=target.provider,
        masked_key=mask_secret(key_in.api_key),
        created_at=target.created_at,
        updated_at=target.updated_at
    )

@router.get("/secrets", response_model=List[ApiKeyResponse])
async def list_secret_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists configured API keys for the current user.
    Keys are decrypted strictly in memory to produce a safe masked display.
    """
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == current_user.id)
    )
    keys = result.scalars().all()

    response = []
    for k in keys:
        try:
            decrypted = decrypt_secret(k.encrypted_key)
            masked = mask_secret(decrypted)
        except Exception:
            masked = "••••••••••••"
        response.append(
            ApiKeyResponse(
                id=k.id,
                provider=k.provider,
                masked_key=masked,
                created_at=k.created_at,
                updated_at=k.updated_at
            )
        )
    return response

@router.delete("/secrets/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret_api_key(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Deletes an encrypted provider key from the user's vault."""
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == current_user.id,
            UserApiKey.provider == provider.lower().strip()
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No secret found for provider '{provider}'"
        )

    await db.delete(key)
    await db.commit()
    return None
