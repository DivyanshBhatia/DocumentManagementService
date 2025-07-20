# main.py - Fixed for Python 3.13 compatibility with asyncpg and Neon deployment
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Column, Integer, String, Date, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from pydantic import BaseModel, Field
from datetime import datetime, date, timedelta
from typing import Optional, List
import jwt
import hashlib
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import os
from dotenv import load_dotenv

# Email imports with Python 3.13 compatibility
try:
    import yagmail
    EMAIL_AVAILABLE = True
except ImportError:
    # Fallback for email functionality
    EMAIL_AVAILABLE = False
    print("⚠️ Email functionality not available - yagmail not installed")

load_dotenv()

# Database Configuration - Fixed for Neon with Python 3.13 using asyncpg
DATABASE_URL = os.getenv("DATABASE_URL")

# If no DATABASE_URL in env, construct from your connection string
if not DATABASE_URL:
    DATABASE_URL = "postgresql://neondb_owner:npg_LuK5zQJy3Ftg@ep-lingering-leaf-a1qcmj51-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"

# Clean up the DATABASE_URL if it contains psql command wrapper
if DATABASE_URL.startswith('psql '):
    # Extract the actual URL from the psql command
    import re
    url_match = re.search(r"'([^']+)'", DATABASE_URL)
    if url_match:
        DATABASE_URL = url_match.group(1)

# Convert to asyncpg format if using postgresql://
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

print(f"Connecting to database: {ASYNC_DATABASE_URL.split('@')[0]}@***")

try:
    # Create async engine with asyncpg for Python 3.13 compatibility
    async_engine = create_async_engine(
        ASYNC_DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "server_settings": {
                "application_name": "document-management-api",
            }
        },
        echo=False  # Disable SQL logging for production
    )

    # For synchronous operations, we'll also create a sync engine with psycopg2
    # Try with the latest psycopg2-binary that might work
    try:
        from sqlalchemy import create_engine
        sync_engine = create_engine(
            DATABASE_URL,
            pool_size=3,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={
                "sslmode": "require",
                "application_name": "document-management-api-sync",
                "connect_timeout": 10,
            },
            echo=False
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
        SYNC_DB_AVAILABLE = True
        print("✅ Synchronous database connection configured!")
    except Exception as sync_e:
        print(f"⚠️ Sync database unavailable: {sync_e}")
        SessionLocal = None
        sync_engine = None
        SYNC_DB_AVAILABLE = False

    # Async session maker
    AsyncSessionLocal = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    Base = declarative_base()
    DATABASE_AVAILABLE = True
    print("✅ Async database connection successful!")

except Exception as e:
    print(f"❌ Database connection error: {str(e)}")
    print("📋 Troubleshooting steps:")
    print("1. Install asyncpg for Python 3.13 support:")
    print("   pip install asyncpg")
    print("2. Or downgrade Python to 3.11/3.12:")
    print("   pyenv install 3.12.7")
    print("3. Check your requirements.txt")

    # Create dummy engines for build process
    async_engine = None
    sync_engine = None
    SessionLocal = None
    AsyncSessionLocal = None
    Base = declarative_base()
    DATABASE_AVAILABLE = False
    SYNC_DB_AVAILABLE = False

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
STATIC_TOKEN_STRING = "alphabeta"

# Email Configuration
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@company.com")

# Database Models
class Document(Base):
    __tablename__ = "documents"

    sno = Column(Integer, primary_key=True, index=True, autoincrement=True)
    document_type = Column(String(100), nullable=False)
    document_owner = Column(String(100), nullable=False)
    document_number = Column(String(50), unique=True, nullable=False)
    expiry_date = Column(Date, nullable=False)
    action_due_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    role = Column(String(20), nullable=False, default="user")  # admin, owner, user
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables only if engine is available
async def create_tables():
    if async_engine and DATABASE_AVAILABLE:
        try:
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("✅ Database tables created/verified successfully!")
        except Exception as e:
            print(f"⚠️ Could not create tables: {str(e)}")

# Pydantic Models
class DocumentCreate(BaseModel):
    document_type: str = Field(..., max_length=100)
    document_owner: str = Field(..., max_length=100)
    document_number: str = Field(..., max_length=50)
    expiry_date: date
    action_due_date: date

class DocumentUpdate(BaseModel):
    document_type: Optional[str] = Field(None, max_length=100)
    document_owner: Optional[str] = Field(None, max_length=100)
    document_number: Optional[str] = Field(None, max_length=50)
    expiry_date: Optional[date] = None
    action_due_date: Optional[date] = None

class DocumentResponse(BaseModel):
    sno: int
    document_type: str
    document_owner: str
    document_number: str
    expiry_date: date
    action_due_date: date
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class TokenData(BaseModel):
    username: str
    role: str

# FastAPI App
app = FastAPI(
    title="Document Management API",
    version="1.0.0",
    description="A comprehensive document management system with automated reminders - Powered by Neon"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

# Dependency to get database session
def get_db():
    if not SessionLocal or not SYNC_DB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection not available. Please check database configuration."
        )
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    finally:
        db.close()

# Async database dependency
async def get_async_db():
    if not AsyncSessionLocal or not DATABASE_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Async database connection not available."
        )
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}"
            )
        finally:
            await session.close()

# JWT Token validation
def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

        # Check if token contains the static string
        if payload.get("static_string") != STATIC_TOKEN_STRING:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token - missing required static string"
            )

        username = payload.get("sub")
        role = payload.get("role", "user")

        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

        return TokenData(username=username, role=role)

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

# Helper function to send email notifications using yagmail
async def send_email_notification(subject: str, body: str, recipients: List[str]):
    if not EMAIL_AVAILABLE:
        print("Email functionality not available - yagmail not installed")
        return False

    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("Email credentials not configured, skipping email notification")
        return False

    try:
        # Initialize yagmail SMTP client
        yag = yagmail.SMTP(SMTP_USERNAME, SMTP_PASSWORD)

        # Send email to all recipients
        yag.send(
            to=recipients,
            subject=subject,
            contents=body
        )

        yag.close()
        return True
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        return False

# Reminder check function using async database
async def check_expiry_reminders():
    print(f"Running expiry reminder check at {datetime.now()}")

    if not AsyncSessionLocal or not DATABASE_AVAILABLE:
        print("Async database connection not available for reminder check")
        return

    async with AsyncSessionLocal() as db:
        try:
            from sqlalchemy import select
            # Get documents expiring within 30 days
            thirty_days_from_now = date.today() + timedelta(days=30)

            # Use async query
            result = await db.execute(
                select(Document).filter(
                    Document.expiry_date <= thirty_days_from_now,
                    Document.expiry_date >= date.today()
                )
            )
            expiring_docs = result.scalars().all()

            if not expiring_docs:
                print("No documents expiring within 30 days")
                return

            # Get admin and owner users
            user_result = await db.execute(
                select(User).filter(User.role.in_(["admin", "owner"]))
            )
            admin_users = user_result.scalars().all()

            if not admin_users:
                print("No admin or owner users found")
                return

            # Prepare email content
            email_body = f"""
            <html>
            <body>
                <h2>📋 Document Expiry Reminder</h2>
                <p>The following {len(expiring_docs)} document(s) are expiring within 30 days:</p>
                <table border="1" style="border-collapse: collapse; width: 100%;">
                    <tr style="background-color: #f2f2f2;">
                        <th style="padding: 8px;">Document Type</th>
                        <th style="padding: 8px;">Owner</th>
                        <th style="padding: 8px;">Document Number</th>
                        <th style="padding: 8px;">Expiry Date</th>
                        <th style="padding: 8px;">Action Due Date</th>
                    </tr>
            """

            for doc in expiring_docs:
                days_until_expiry = (doc.expiry_date - date.today()).days
                color = "#ffebee" if days_until_expiry <= 7 else "#fff3e0" if days_until_expiry <= 14 else "#f3e5f5"

                email_body += f"""
                    <tr style="background-color: {color};">
                        <td style="padding: 8px;">{doc.document_type}</td>
                        <td style="padding: 8px;">{doc.document_owner}</td>
                        <td style="padding: 8px;">{doc.document_number}</td>
                        <td style="padding: 8px;">{doc.expiry_date} ({days_until_expiry} days)</td>
                        <td style="padding: 8px;">{doc.action_due_date}</td>
                    </tr>
                """

            email_body += """
                </table>
                <br>
                <p><strong>⚠️ Please take necessary action before the expiry dates.</strong></p>
                <p><small>This is an automated reminder from your Document Management System.</small></p>
            </body>
            </html>
            """

            recipients = [user.email for user in admin_users]

            success = await send_email_notification(
                subject=f"🔔 Document Expiry Reminder - {len(expiring_docs)} documents expiring soon",
                body=email_body,
                recipients=recipients
            )

            if success:
                print(f"Reminder sent for {len(expiring_docs)} documents to {len(recipients)} recipients")
            else:
                print("Failed to send reminder email")

        except Exception as e:
            print(f"Error in reminder check: {str(e)}")

# Scheduler setup
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    # Create tables
    await create_tables()

    # Only start scheduler if database is available
    if AsyncSessionLocal and DATABASE_AVAILABLE:
        try:
            # Schedule daily reminder check at 9 AM UTC
            scheduler.add_job(
                check_expiry_reminders,
                CronTrigger(hour=9, minute=0),
                id="daily_reminder_check"
            )
            scheduler.start()
            print("✅ Scheduler started - Daily reminder check at 9:00 AM UTC")
        except Exception as e:
            print(f"Failed to start scheduler: {str(e)}")
    else:
        print("⚠️ Scheduler not started - Database connection unavailable")

@app.on_event("shutdown")
async def shutdown_event():
    try:
        if scheduler.running:
            scheduler.shutdown()
            print("Scheduler shut down successfully")
    except Exception as e:
        print(f"Error shutting down scheduler: {str(e)}")

    # Close async engine
    if async_engine:
        await async_engine.dispose()

# API Endpoints

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Document Management API - Powered by Neon Database",
        "version": "1.0.0",
        "status": "active",
        "docs": "/docs",
        "health": "/health",
        "database": "Neon PostgreSQL with asyncpg",
        "database_available": DATABASE_AVAILABLE,
        "sync_db_available": SYNC_DB_AVAILABLE,
        "email_support": EMAIL_AVAILABLE,
        "python_version": "3.13"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint with database connectivity test"""
    db_status = "disconnected"
    db_details = {}

    if AsyncSessionLocal and DATABASE_AVAILABLE:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(text("SELECT version(), current_database(), current_user"))
                row = result.fetchone()
                db_status = "connected"
                db_details = {
                    "version": row[0].split()[0:2] if row[0] else "Unknown",
                    "database": row[1] if row[1] else "Unknown",
                    "user": row[2] if row[2] else "Unknown"
                }
        except Exception as e:
            db_status = f"error: {str(e)}"

    return {
        "status": "healthy" if DATABASE_AVAILABLE else "degraded",
        "timestamp": datetime.utcnow(),
        "database": db_status,
        "database_details": db_details,
        "scheduler": "running" if scheduler.running else "stopped",
        "email_support": EMAIL_AVAILABLE,
        "python_version": "3.13",
        "async_db": DATABASE_AVAILABLE,
        "sync_db": SYNC_DB_AVAILABLE
    }

@app.post("/auth/token")
async def create_access_token(username: str, role: str = "user"):
    """Create JWT token for authentication"""
    payload = {
        "sub": username,
        "role": role,
        "static_string": STATIC_TOKEN_STRING,
        "exp": datetime.utcnow() + timedelta(hours=24),
        "iat": datetime.utcnow()
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 86400,  # 24 hours
        "username": username,
        "role": role
    }

# Document endpoints with proper error handling
@app.post("/documents/", response_model=DocumentResponse)
async def create_document(
    document: DocumentCreate,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(verify_token)
):
    """Create a new document"""
    try:
        # Check if document number already exists
        existing_doc = db.query(Document).filter(
            Document.document_number == document.document_number
        ).first()

        if existing_doc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document number already exists"
            )

        # Validate dates
        if document.expiry_date < date.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Expiry date cannot be in the past"
            )

        if document.action_due_date > document.expiry_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Action due date cannot be after expiry date"
            )

        db_document = Document(**document.dict())
        db.add(db_document)
        db.commit()
        db.refresh(db_document)

        return db_document
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create document: {str(e)}"
        )

@app.get("/documents/", response_model=List[DocumentResponse])
async def get_documents(
    skip: int = 0,
    limit: int = 100,
    document_type: Optional[str] = None,
    owner: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(verify_token)
):
    """Retrieve all documents with pagination and filtering"""
    query = db.query(Document)

    if document_type:
        query = query.filter(Document.document_type.ilike(f"%{document_type}%"))

    if owner:
        query = query.filter(Document.document_owner.ilike(f"%{owner}%"))

    documents = query.offset(skip).limit(limit).all()
    return documents

@app.get("/documents/{sno}", response_model=DocumentResponse)
async def get_document(
    sno: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(verify_token)
):
    """Retrieve a specific document by SNo"""
    document = db.query(Document).filter(Document.sno == sno).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with SNo {sno} not found"
        )
    return document

@app.put("/documents/{sno}", response_model=DocumentResponse)
async def update_document(
    sno: int,
    document_update: DocumentUpdate,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(verify_token)
):
    """Update a document"""
    document = db.query(Document).filter(Document.sno == sno).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with SNo {sno} not found"
        )

    try:
        # Update only provided fields
        update_data = document_update.dict(exclude_unset=True)

        # Validate dates if provided
        if "expiry_date" in update_data and update_data["expiry_date"] < date.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Expiry date cannot be in the past"
            )

        # Check if document number is being updated and if it already exists
        if "document_number" in update_data:
            existing_doc = db.query(Document).filter(
                Document.document_number == update_data["document_number"],
                Document.sno != sno
            ).first()

            if existing_doc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Document number already exists"
                )

        for field, value in update_data.items():
            setattr(document, field, value)

        document.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(document)

        return document
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update document: {str(e)}"
        )

@app.delete("/documents/{sno}")
async def delete_document(
    sno: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(verify_token)
):
    """Delete a document"""
    document = db.query(Document).filter(Document.sno == sno).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with SNo {sno} not found"
        )

    try:
        document_info = {
            "sno": document.sno,
            "document_type": document.document_type,
            "document_number": document.document_number
        }

        db.delete(document)
        db.commit()
        return {
            "message": "Document deleted successfully",
            "deleted_document": document_info
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(e)}"
        )

@app.post("/reminder/check")
async def manual_reminder_check(
    current_user: TokenData = Depends(verify_token)
):
    """Manually trigger reminder check (admin only)"""
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or owner can trigger manual reminder check"
        )

    if not DATABASE_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available for reminder check"
        )

    await check_expiry_reminders()
    return {"message": "Reminder check completed"}

@app.get("/documents/expiring/soon")
async def get_expiring_documents(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(verify_token)
):
    """Get documents expiring within specified days"""
    target_date = date.today() + timedelta(days=days)

    expiring_docs = db.query(Document).filter(
        Document.expiry_date <= target_date,
        Document.expiry_date >= date.today()
    ).all()

    return {
        "expiring_documents": expiring_docs,
        "count": len(expiring_docs),
        "days_ahead": days
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
