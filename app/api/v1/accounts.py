"""Accounts API endpoints"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workspace_context import WorkspaceContext
from app.core.workspace_deps import get_api_workspace, WorkspaceRoute
from app.database import get_db
from app.schemas.account import AccountCreate, AccountUpdate, AccountResponse
from app.services import account_service


router = APIRouter(route_class=WorkspaceRoute, prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountResponse])
async def get_accounts(
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)]
):
    """Get all accounts"""
    accounts = await account_service.get_accounts(context, db)
    return accounts


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)]
):
    """Create a new account"""
    account = await account_service.create_account(context, db, account_data)
    return account


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)]
):
    """Get account by ID"""
    account = await account_service.get_account(context, db, account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )
    return account


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: int,
    account_data: AccountUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)]
):
    """Update account"""
    account = await account_service.update_account(context, db, account_id, account_data)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)]
):
    """Delete account"""
    success = await account_service.delete_account(context, db, account_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )
    return None
