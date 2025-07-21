# main.py - Fixed database table creation for Python 3.13 compatibility
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
import io

# PDF generation imports
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    PDF_AVAILABLE = True
except ImportError:
    # Fallback for PDF functionality
    PDF_AVAILABLE = False
    print("⚠️ PDF functionality not available - reportlab not installed")

# Email imports with Python 3.13 compatibility
try:
    import yagmail
    EMAIL_AVAILABLE = True
except ImportError:
    # Fallback for email functionality
    EMAIL_AVAILABLE = False
    print("⚠️ Email functionality not available - yagmail not installed")

load_dotenv()

# Database Configuration - Fixed for Neon with Python 3.13 using psycopg v3
DATABASE_URL = os.getenv("DATABASE_URL")

# If no DATABASE_URL in env, construct from your connection string
if not DATABASE_URL:
    print(f"Connecting to database: Failed as unable to find DATABASE_URL")

# Clean up the DATABASE_URL if it contains psql command wrapper
if DATABASE_URL.startswith('psql '):
    # Extract the actual URL from the psql command
    import re
    url_match = re.search(r"'([^']+)'", DATABASE_URL)
    if url_match:
        DATABASE_URL = url_match.group(1)

# For psycopg v3 async support
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

print(f"Connecting to database: {ASYNC_DATABASE_URL.split('@')[0]}@***")

# Initialize global variables
async_engine = None
sync_engine = None
SessionLocal = None
AsyncSessionLocal = None
Base = declarative_base()
DATABASE_AVAILABLE = False
SYNC_DB_AVAILABLE = False

# Database Models (Define before engine creation)
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

# Database connection setup
try:
    # Create async engine with psycopg v3 for Python 3.13 compatibility
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

    # For synchronous operations with psycopg2-binary
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

    DATABASE_AVAILABLE = True
    print("✅ Async database connection successful with psycopg v3!")

except Exception as e:
    print(f"❌ Database connection error: {str(e)}")
    print("📋 Troubleshooting steps:")
    print("1. Install psycopg v3 for Python 3.13 support:")
    print("   pip install 'psycopg[binary]' 'psycopg[pool]'")
    print("2. Or use alternative driver aiopg:")
    print("   pip install aiopg")
    print("3. Check your requirements.txt")

    # Create dummy engines for build process
    async_engine = None
    sync_engine = None
    SessionLocal = None
    AsyncSessionLocal = None
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

# Enhanced table creation function
async def create_tables():
    """Create tables in both async and sync engines"""
    tables_created = False

    # Try async table creation first
    if async_engine and DATABASE_AVAILABLE:
        try:
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("✅ Database tables created/verified successfully (async)!")
            tables_created = True
        except Exception as e:
            print(f"⚠️ Could not create async tables: {str(e)}")

    # Try sync table creation if async failed or if we have sync engine
    if sync_engine and SYNC_DB_AVAILABLE and not tables_created:
        try:
            Base.metadata.create_all(bind=sync_engine)
            print("✅ Database tables created/verified successfully (sync)!")
            tables_created = True
        except Exception as e:
            print(f"⚠️ Could not create sync tables: {str(e)}")

    if not tables_created:
        print("❌ Failed to create tables in both async and sync engines")

    return tables_created

# Function to ensure tables exist before operations
def ensure_tables_exist():
    """Ensure tables exist in sync engine before operations"""
    if sync_engine and SYNC_DB_AVAILABLE:
        try:
            # Check if tables exist
            from sqlalchemy import inspect
            inspector = inspect(sync_engine)
            existing_tables = inspector.get_table_names()

            if 'documents' not in existing_tables or 'users' not in existing_tables:
                print("📋 Creating missing tables...")
                Base.metadata.create_all(bind=sync_engine)
                print("✅ Tables created successfully!")

            return True
        except Exception as e:
            print(f"❌ Error ensuring tables exist: {str(e)}")
            return False
    return False

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

# Enhanced dependency to get database session with table verification
def get_db():
    if not SessionLocal or not SYNC_DB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection not available. Please check database configuration."
        )

    # Ensure tables exist before proceeding
    if not ensure_tables_exist():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database tables not available. Please check database setup."
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

def generate_pdf_report(documents: List[Document]) -> io.BytesIO:
    """Generate PDF report of documents"""
    if not PDF_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF functionality not available - reportlab not installed"
        )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    # Get styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=1,  # Center alignment
    )

    # Title
    title = Paragraph("Document Management Report", title_style)
    elements.append(title)

    # Add generation date
    date_style = ParagraphStyle(
        'DateStyle',
        parent=styles['Normal'],
        fontSize=10,
        alignment=1,  # Center alignment
        spaceAfter=20,
    )

    generation_date = Paragraph(
        f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        date_style
    )
    elements.append(generation_date)

    elements.append(Spacer(1, 12))

    if not documents:
        no_docs = Paragraph("No documents found.", styles['Normal'])
        elements.append(no_docs)
    else:
        # Summary - Fixed to handle None expiry dates
        total_docs = len(documents)
        expired_docs = len([
            doc for doc in documents
            if doc.expiry_date and doc.expiry_date < date.today()
        ])
        expiring_soon = len([
            doc for doc in documents
            if doc.expiry_date and
            doc.expiry_date <= date.today() + timedelta(days=30) and
            doc.expiry_date >= date.today()
        ])

        summary = Paragraph(
            f"<b>Summary:</b> Total Documents: {total_docs} | Expired: {expired_docs} | Expiring within 30 days: {expiring_soon}",
            styles['Normal']
        )
        elements.append(summary)
        elements.append(Spacer(1, 20))

        # Create table data
        data = [
            ['S.No', 'Type', 'Owner', 'Document Number', 'Expiry Date', 'Action Due', 'Status']
        ]

        for document_item in documents:
            # Determine status based on expiry date
            if document_item.expiry_date:
                days_until_expiry = (document_item.expiry_date - date.today()).days
                expiry_str = document_item.expiry_date.strftime('%Y-%m-%d')

                if days_until_expiry < 0:
                    document_status = "EXPIRED"
                elif days_until_expiry <= 7:
                    document_status = "URGENT"
                elif days_until_expiry <= 30:
                    document_status = "WARNING"
                else:
                    document_status = "OK"
            else:
                expiry_str = "N/A"
                document_status = "NO DATE"

            # Handle None action due dates
            action_due_str = document_item.action_due_date.strftime('%Y-%m-%d') if document_item.action_due_date else "N/A"

            data.append([
                str(document_item.sno),
                document_item.document_type or "N/A",
                document_item.document_owner or "N/A",
                document_item.document_number or "N/A",
                expiry_str,
                action_due_str,
                document_status
            ])

        # Create table
        table = Table(data)

        # Style the table
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))

        # Add row coloring based on status
        for i, document_item in enumerate(documents, start=1):
            if document_item.expiry_date:
                days_until_expiry = (document_item.expiry_date - date.today()).days
                if days_until_expiry < 0:
                    # Expired - red background
                    table.setStyle(TableStyle([('BACKGROUND', (0, i), (-1, i), colors.lightpink)]))
                elif days_until_expiry <= 7:
                    # Urgent - orange background
                    table.setStyle(TableStyle([('BACKGROUND', (0, i), (-1, i), colors.orange)]))
                elif days_until_expiry <= 30:
                    # Warning - yellow background
                    table.setStyle(TableStyle([('BACKGROUND', (0, i), (-1, i), colors.lightyellow)]))
            else:
                # No expiry date - gray background
                table.setStyle(TableStyle([('BACKGROUND', (0, i), (-1, i), colors.lightgrey)]))

        elements.append(table)

        # Add legend
        elements.append(Spacer(1, 20))
        legend = Paragraph(
            "<b>Status Legend:</b><br/>"
            "• EXPIRED: Document has already expired<br/>"
            "• URGENT: Expires within 7 days<br/>"
            "• WARNING: Expires within 30 days<br/>"
            "• OK: More than 30 days until expiry<br/>"
            "• NO DATE: No expiry date set",
            styles['Normal']
        )
        elements.append(legend)

    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer


# Scheduler setup
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    # Create tables with enhanced error handling
    print("🚀 Starting Document Management API...")
    tables_created = await create_tables()

    if not tables_created:
        print("⚠️ Warning: Tables may not be properly created. API will attempt to create them on-demand.")

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
        "database": "Neon PostgreSQL with psycopg v3",
        "database_available": DATABASE_AVAILABLE,
        "sync_db_available": SYNC_DB_AVAILABLE,
        "email_support": EMAIL_AVAILABLE,
        "pdf_support": PDF_AVAILABLE,
        "python_version": "3.13"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint with database connectivity test"""
    db_status = "disconnected"
    db_details = {}
    table_status = {}

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

                # Check if tables exist
                try:
                    doc_count = await db.execute(text("SELECT COUNT(*) FROM documents"))
                    user_count = await db.execute(text("SELECT COUNT(*) FROM users"))
                    table_status = {
                        "documents_table": "exists",
                        "users_table": "exists",
                        "document_count": doc_count.scalar(),
                        "user_count": user_count.scalar()
                    }
                except Exception as table_e:
                    table_status = {"error": f"Tables may not exist: {str(table_e)}"}

        except Exception as e:
            db_status = f"error: {str(e)}"

    return {
        "status": "healthy" if DATABASE_AVAILABLE else "degraded",
        "timestamp": datetime.utcnow(),
        "database": db_status,
        "database_details": db_details,
        "table_status": table_status,
        "scheduler": "running" if scheduler.running else "stopped",
        "email_support": EMAIL_AVAILABLE,
        "pdf_support": PDF_AVAILABLE,
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

# New endpoint to manually create tables
@app.post("/admin/create-tables")
async def create_tables_endpoint():
    """Manually create database tables (development/debugging endpoint)"""
    try:
        tables_created = await create_tables()

        # Also ensure sync tables exist
        sync_tables_created = ensure_tables_exist()

        return {
            "message": "Table creation attempted",
            "async_tables_created": tables_created,
            "sync_tables_created": sync_tables_created,
            "database_available": DATABASE_AVAILABLE,
            "sync_db_available": SYNC_DB_AVAILABLE
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create tables: {str(e)}"
        )

# Document endpoints with proper error handling - Updated to sort by expiry date
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
    """Retrieve all documents with pagination and filtering - sorted by earliest expiry date first"""
    query = db.query(Document)

    if document_type:
        query = query.filter(Document.document_type.ilike(f"%{document_type}%"))

    if owner:
        query = query.filter(Document.document_owner.ilike(f"%{owner}%"))

    # Order by expiry date (earliest first), then by action due date
    query = query.order_by(
        Document.expiry_date.asc().nulls_last(),
        Document.action_due_date.asc().nulls_last()
    )
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

# Download report endpoint
@app.get("/documents/download-report/")
async def download_documents_report(
    document_type: Optional[str] = None,
    owner: Optional[str] = None,
    status_filter: Optional[str] = None,  # expired, urgent, warning, ok
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(verify_token)
):
    """Download PDF report of documents with optional filtering"""

    # Build query with filters
    query = db.query(Document)

    if document_type:
        query = query.filter(Document.document_type.ilike(f"%{document_type}%"))

    if owner:
        query = query.filter(Document.document_owner.ilike(f"%{owner}%"))

    # Apply status filter if specified
    if status_filter:
        today = date.today()
        if status_filter.lower() == "expired":
            query = query.filter(Document.expiry_date < today)
        elif status_filter.lower() == "urgent":
            urgent_date = today + timedelta(days=7)
            query = query.filter(
                Document.expiry_date >= today,
                Document.expiry_date <= urgent_date
            )
        elif status_filter.lower() == "warning":
            warning_date = today + timedelta(days=30)
            urgent_date = today + timedelta(days=7)
            query = query.filter(
                Document.expiry_date > urgent_date,
                Document.expiry_date <= warning_date
            )
        elif status_filter.lower() == "ok":
            ok_date = today + timedelta(days=30)
            query = query.filter(Document.expiry_date > ok_date)

    # Order by expiry date (earliest first)
    query = query.order_by(
        Document.expiry_date.asc().nulls_last(),
        Document.action_due_date.asc().nulls_last()
    )

    documents = query.all()

    try:
        # Generate PDF
        pdf_buffer = generate_pdf_report(documents)

        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"documents_report_{timestamp}.pdf"

        # Return PDF as response
        return StreamingResponse(
            io.BytesIO(pdf_buffer.read()),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF report: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
