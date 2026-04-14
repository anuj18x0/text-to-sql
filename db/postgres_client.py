import os
import logging
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

# Module-level singletons
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None

def get_db_engine() -> Engine:
    """
    Initializes and returns a SQLAlchemy engine for PostgreSQL.
    Supports Cloud (Supabase) and Local PostgreSQL modes.
    
    Priority:
    1. If DB_MODE="cloud" -> Use Supabase credentials
    2. If DB_MODE="local" -> Use DATABASE_LOCAL_URL
    """
    global _engine
    if _engine is not None:
        return _engine

    db_mode = os.getenv("DB_MODE", "cloud").lower()

    if db_mode == "cloud":
        supabase_id = os.getenv("SUPABASE_PROJECT_ID")
        supabase_pw = os.getenv("SUPABASE_PASSWORD")
        supabase_host = os.getenv("SUPABASE_HOST")
        
        if not (supabase_id and supabase_pw):
            raise ValueError("SUPABASE_PROJECT_ID and SUPABASE_PASSWORD are required for cloud mode.")

        host = supabase_host or f"db.{supabase_id}.supabase.co"
        
        # Determine username based on host (pooler uses specific format)
        if "pooler.supabase.com" in host:
            username = f"postgres.{supabase_id}"
        else:
            username = "postgres"
            
        port = os.getenv("SUPABASE_PORT", "5432")
        encoded_pw = quote_plus(supabase_pw)
        url = f"postgresql://{username}:{encoded_pw}@{host}:{port}/postgres"
        logger.info("Postgres: Mode=Cloud (Host: %s)", host)
        _engine = create_engine(url)
        
    else:
        # Local Mode - PostgreSQL Only (No SQLite)
        url = os.getenv("DATABASE_LOCAL_URL")
        if not url:
            # Fallback to a standard local postgres URL if not provided
            url = "postgresql://postgres:postgres@localhost:5432/olist"
            logger.warning("DATABASE_LOCAL_URL not set; defaulting to: %s", url)
        
        logger.info("Postgres: Mode=Local (Context: PostgreSQL)")
        _engine = create_engine(url)

    return _engine

def get_db_session() -> Session:
    """Return a new Session bound to the shared engine."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=get_db_engine()
        )
    return _SessionLocal()
