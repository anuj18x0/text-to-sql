import os
import logging
from typing import Optional
import chromadb
import chromadb.utils.embedding_functions as embedding_functions
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

def get_embedding_function():
    """Returns the standardized Google Gemini embedding function."""
    embedding_model = os.getenv("EMBEDDING_MODEL")
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set in environment variables.")
        
    return embedding_functions.GoogleGeminiEmbeddingFunction(
        api_key_env_var="GEMINI_API_KEY",
        model_name=embedding_model,
        vertexai=False
    )

def get_chroma_client() -> chromadb.ClientAPI:
    """
    Initializes and returns a ChromaDB client based on environment variables.
    
    Priority:
    1. If CHROMA_MODE="cloud" or CHROMA_API_KEY is present -> CloudClient
    2. Otherwise -> PersistentClient
    """
    chroma_mode = os.getenv("CHROMA_MODE", "").lower()
    chroma_api_key = os.getenv("CHROMA_API_KEY")
    chroma_tenant = os.getenv("CHROMA_TENANT", "default_tenant")
    chroma_database = os.getenv("CHROMA_DATABASE", "default_database")
    chroma_host = os.getenv("CHROMA_HOST", "europe-west1.gcp.trychroma.com")
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./db/chroma_store")

    # Force cloud if explicitly set or if API key is found
    if chroma_mode == "cloud" or (chroma_mode != "local" and chroma_api_key):
        logger.info("ChromaDB: Mode=Cloud (Host: %s)", chroma_host)
        return chromadb.CloudClient(
            cloud_port=443,
            cloud_host=chroma_host,
            api_key=chroma_api_key,
            tenant=chroma_tenant,
            database=chroma_database,
        )
    else:
        logger.info("ChromaDB: Mode=Local (Path: %s)", persist_dir)
        return chromadb.PersistentClient(path=persist_dir)
