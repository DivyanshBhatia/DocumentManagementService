# main.py - Updated for Render deployment with PostgreSQL
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel, Field
from datetime import datetime, date, timedelta
from typing import Optional, List
import jwt
import hashlib
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
import os
from dotenv import load_dotenv

load_dotenv()

# Database Configuration - Updated for PostgreSQL on Render
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://username:password@localhost/document_management")

# Fix for Render's DATABASE_URL format
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

try:
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
except Exception as e:
    print(f"Database connection error: {str(e)}")
    # Create a dummy engine for build process
    engine = None
    SessionLocal = None
    Base = declarative_base()

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")
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
if engine:
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"Could not create tables: {str(e)}")

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
    description="A comprehensive document management system with automated reminders"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

# Dependency to get database session
def get_db():
    if not SessionLocal:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection not available"
        )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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

# Helper function to send email notifications
async def send_email_notification(subject: str, body: str, recipients: List[str]):
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("Email credentials not configured, skipping email notification")
        return False

    try:
        msg = MimeMultipart()
        msg['From'] = SMTP_USERNAME
        msg['Subject'] = subject
        msg.attach(MimeText(body, 'html'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)

        for recipient in recipients:
            msg['To'] = recipient
            server.send_message(msg)
            del msg['To']

        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        return False

# Reminder check function
async def check_expiry_reminders():
    print(f"Running expiry reminder check at {datetime.now()}")

    if not SessionLocal:
        print("Database connection not available for reminder check")
        return

    db = SessionLocal()
    try:
        # Get documents expiring within 30 days
        thirty_days_from_now = date.today() + timedelta(days=30)

        expiring_docs = db.query(Document).filter(
            Document.expiry_date <= thirty_days_from_now,
            Document.expiry_date >= date.today()
        ).all()

        if not expiring_docs:
            print("No documents expiring within 30 days")
            return

        # Get admin and owner users
        admin_users = db.query(User).filter(
            User.role.in_(["admin", "owner"])
        ).all()

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
    finally:
        db.close()

# Scheduler setup
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    # Only start scheduler if database is available
    if SessionLocal:
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
        scheduler.shutdown()
        print("Scheduler shut down successfully")
    except Exception as e:
        print(f"Error shutting down scheduler: {str(e)}")

# API Endpoints

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Document Management API",
        "version": "1.0.0",
        "status": "active",
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    db_status = "connected" if SessionLocal else "disconnected"
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow(),
        "database": db_status,
        "scheduler": "running" if scheduler.running else "stopped"
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

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
