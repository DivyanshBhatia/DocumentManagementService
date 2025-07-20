# main.py
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

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://username:password@localhost/document_management")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
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

# Create tables
Base.metadata.create_all(bind=engine)

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
app = FastAPI(title="Document Management API", version="1.0.0")

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
        email_body = """
        <html>
        <body>
            <h2>Document Expiry Reminder</h2>
            <p>The following documents are expiring within 30 days:</p>
            <table border="1" style="border-collapse: collapse;">
                <tr>
                    <th>Document Type</th>
                    <th>Owner</th>
                    <th>Document Number</th>
                    <th>Expiry Date</th>
                    <th>Action Due Date</th>
                </tr>
        """

        for doc in expiring_docs:
            email_body += f"""
                <tr>
                    <td>{doc.document_type}</td>
                    <td>{doc.document_owner}</td>
                    <td>{doc.document_number}</td>
                    <td>{doc.expiry_date}</td>
                    <td>{doc.action_due_date}</td>
                </tr>
            """

        email_body += """
            </table>
            <p>Please take necessary action before the expiry dates.</p>
        </body>
        </html>
        """

        recipients = [user.email for user in admin_users]

        await send_email_notification(
            subject="Document Expiry Reminder",
            body=email_body,
            recipients=recipients
        )

        print(f"Reminder sent for {len(expiring_docs)} documents to {len(recipients)} recipients")

    except Exception as e:
        print(f"Error in reminder check: {str(e)}")
    finally:
        db.close()

# Scheduler setup
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    # Schedule daily reminder check at 9 AM
    scheduler.add_job(
        check_expiry_reminders,
        CronTrigger(hour=9, minute=0),
        id="daily_reminder_check"
    )
    scheduler.start()
    print("Scheduler started - Daily reminder check at 9:00 AM")

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()

# API Endpoints

@app.post("/auth/token")
async def create_access_token(username: str, role: str = "user"):
    """Create JWT token for authentication (for testing purposes)"""
    payload = {
        "sub": username,
        "role": role,
        "static_string": STATIC_TOKEN_STRING,
        "exp": datetime.utcnow() + timedelta(hours=24)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

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

        db_document = Document(**document.dict())
        db.add(db_document)
        db.commit()
        db.refresh(db_document)

        return db_document
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
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(verify_token)
):
    """Retrieve all documents with pagination"""
    documents = db.query(Document).offset(skip).limit(limit).all()
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
            detail="Document not found"
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
            detail="Document not found"
        )

    try:
        # Update only provided fields
        update_data = document_update.dict(exclude_unset=True)

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
            detail="Document not found"
        )

    try:
        db.delete(document)
        db.commit()
        return {"message": "Document deleted successfully"}
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
