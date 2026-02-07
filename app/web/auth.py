"""Web authentication routes for Jinja2 + HTMX"""
from typing import Annotated
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate
from app.core.deps import get_current_user_from_cookie, get_current_user_from_cookie_required
from app.services import auth_service, user_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    user: Annotated[User | None, Depends(get_current_user_from_cookie)]
):
    """
    Display login page.
    Redirects to dashboard if already authenticated.
    """
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request}
    )


@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Process login form submission (HTMX).
    Returns redirect header on success or error message on failure.
    """
    try:
        # Authenticate user using service
        user = await auth_service.authenticate_user(username, password, db)
        
        # Create access token
        token = await auth_service.create_user_access_token(user)
        
        # For HTMX - return redirect via header and set cookie
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = "/dashboard"
        response.set_cookie(
            key="access_token",
            value=token.access_token,
            httponly=True,
            samesite="lax",
            max_age=1800  # 30 minutes (same as token expiry)
        )
        return response
        
    except ValueError as e:
        # Return error message as HTML
        error_message = str(e)
        
        return HTMLResponse(
            content=f'''
            <div class="alert alert-error fade-in">
                <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>{error_message}</span>
            </div>
            ''',
            status_code=200
        )


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    user: Annotated[User | None, Depends(get_current_user_from_cookie)]
):
    """
    Display registration page.
    Redirects to dashboard if already authenticated.
    """
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    
    return templates.TemplateResponse(
        "auth/register.html",
        {"request": request}
    )


@router.post("/register")
async def register_post(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    full_name: str | None = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Process registration form submission (HTMX).
    Returns redirect header on success or error message on failure.
    """
    try:
        # Validate password confirmation
        if password != password_confirm:
            raise ValueError("Пароли не совпадают")
        
        # Create user data
        user_data = UserCreate(
            email=email,
            username=username,
            password=password,
            full_name=full_name if full_name else None
        )
        
        # Create user using service
        user = await user_service.create_user(user_data, db)
        
        # Automatically log in the new user
        token = await auth_service.create_user_access_token(user)
        
        # For HTMX - return redirect via header and set cookie
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = "/dashboard"
        response.set_cookie(
            key="access_token",
            value=token.access_token,
            httponly=True,
            samesite="lax",
            max_age=1800  # 30 minutes
        )
        return response
        
    except ValueError as e:
        # Return error message as HTML
        error_message = str(e)
        
        return HTMLResponse(
            content=f'''
            <div class="alert alert-error fade-in">
                <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>{error_message}</span>
            </div>
            ''',
            status_code=200
        )


@router.get("/logout")
async def logout(request: Request):
    """
    Logout user by clearing the cookie and redirecting to login page.
    """
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie(key="access_token")
    return response
