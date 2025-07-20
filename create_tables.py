# create_tables.py - Fixed table creation script
import os
import sys
import asyncio
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, text, inspect
from sqlalchemy.orm import declarative_base  # Updated import
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()

# Database Models
Base = declarative_base()

class Document(Base):
    __tablename__ = "documents"

    sno = Column(Integer, primary_key=True, index=True, autoincrement=True)
    document_type = Column(String(100), nullable=False)
    document_owner = Column(String(100), nullable=False)
    document_number = Column(String(50), unique=True, nullable=False)
    expiry_date = Column(Date, nullable=False)
    action_due_date = Column(Date, nullable=False)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    role = Column(String(20), nullable=False, default="user")
    created_at = Column(DateTime)

def get_clean_database_url():
    """Get clean database URL without extra formatting"""
    DATABASE_URL = os.getenv("DATABASE_URL")

    # If no env var, use hardcoded URL (cleaned)
    if not DATABASE_URL:
        DATABASE_URL = "postgresql://neondb_owner:npg_LuK5zQJy3Ftg@ep-lingering-leaf-a1qcmj51-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"

    # Clean the URL - remove any psql command formatting
    if DATABASE_URL.startswith("psql '"):
        DATABASE_URL = DATABASE_URL[6:]  # Remove "psql '"
    if DATABASE_URL.endswith("'"):
        DATABASE_URL = DATABASE_URL[:-1]  # Remove trailing "'"

    # Remove channel_binding parameter if present (not supported by SQLAlchemy)
    if "&channel_binding=require" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("&channel_binding=require", "")

    return DATABASE_URL

def create_tables_sync():
    """Create tables using synchronous connection"""
    DATABASE_URL = get_clean_database_url()

    # Hide password in logs
    url_parts = DATABASE_URL.split('@')
    if len(url_parts) > 1:
        user_part = url_parts[0].split('//')[-1].split(':')[0]
        host_part = url_parts[1]
        log_url = f"postgresql://{user_part}:***@{host_part}"
    else:
        log_url = "postgresql://***"

    print(f"Connecting to: {log_url}")

    try:
        # Create synchronous engine
        engine = create_engine(
            DATABASE_URL,
            connect_args={"sslmode": "require"},
            echo=False  # Set to True for SQL debugging
        )

        # Test connection first
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Database connection successful!")

        # Create all tables
        Base.metadata.create_all(bind=engine)
        print("✅ Tables created successfully using synchronous connection!")

        # Verify tables exist
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"📋 Existing tables: {tables}")

        # Test connection and get counts
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) as count FROM documents"))
            doc_count = result.fetchone()[0]

            result = conn.execute(text("SELECT COUNT(*) as count FROM users"))
            user_count = result.fetchone()[0]

            print(f"📊 Current counts - Documents: {doc_count}, Users: {user_count}")

        engine.dispose()
        return True

    except Exception as e:
        print(f"❌ Error creating tables: {str(e)}")
        print(f"❌ Full error type: {type(e).__name__}")
        return False

async def create_tables_async():
    """Create tables using async connection"""
    DATABASE_URL = get_clean_database_url()

    # Convert to async URL
    ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

    # Hide password in logs
    url_parts = ASYNC_DATABASE_URL.split('@')
    if len(url_parts) > 1:
        user_part = url_parts[0].split('//')[-1].split(':')[0]
        host_part = url_parts[1]
        log_url = f"postgresql+psycopg://{user_part}:***@{host_part}"
    else:
        log_url = "postgresql+psycopg://***"

    print(f"Async connecting to: {log_url}")

    try:
        # Create async engine - simplified connection args
        engine = create_async_engine(
            ASYNC_DATABASE_URL,
            echo=False  # Set to True for SQL debugging
        )

        # Test connection first
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        print("✅ Async database connection successful!")

        # Create all tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        print("✅ Tables created successfully using async connection!")

        # Verify and test
        async with engine.begin() as conn:
            # Check if tables exist
            result = await conn.execute(text("SELECT COUNT(*) as count FROM documents"))
            doc_count = result.fetchone()[0]

            result = await conn.execute(text("SELECT COUNT(*) as count FROM users"))
            user_count = result.fetchone()[0]

            print(f"📊 Current counts - Documents: {doc_count}, Users: {user_count}")

        await engine.dispose()
        return True

    except Exception as e:
        print(f"❌ Error creating async tables: {str(e)}")
        print(f"❌ Full error type: {type(e).__name__}")
        return False

def main():
    """Main function to create tables"""
    print("🚀 Creating database tables...")
    print("=" * 50)

    # Show the cleaned URL (for debugging)
    clean_url = get_clean_database_url()
    url_parts = clean_url.split('@')
    if len(url_parts) > 1:
        user_part = url_parts[0].split('//')[-1].split(':')[0]
        host_part = url_parts[1]
        log_url = f"postgresql://{user_part}:***@{host_part}"
    else:
        log_url = "postgresql://***"
    print(f"🔗 Using cleaned URL: {log_url}")

    # Try sync first
    print("\n📋 Attempting synchronous table creation...")
    sync_success = create_tables_sync()

    # Try async if sync failed
    if not sync_success:
        print("\n📋 Attempting async table creation...")
        try:
            async_success = asyncio.run(create_tables_async())
        except Exception as e:
            print(f"❌ Async execution failed: {str(e)}")
            async_success = False

        if not async_success:
            print("\n❌ Both sync and async table creation failed!")
            print("\n🔧 Troubleshooting tips:")
            print("   1. Check if your DATABASE_URL environment variable is correct")
            print("   2. Verify network connectivity to the database")
            print("   3. Ensure the database exists and credentials are valid")
            print("   4. Try installing missing dependencies: pip install psycopg2-binary")
            sys.exit(1)

    print("\n✅ Table creation completed successfully!")
    print("\n💡 You can now run your FastAPI application:")
    print("   python main.py")
    print("   or")
    print("   uvicorn main:app --reload")

if __name__ == "__main__":
    main()
