import os
from dotenv import load_dotenv

os.environ["ANONYMIZED_TELEMETRY"] = "False"

load_dotenv()

class Settings:
    DB_DRIVER = os.getenv("DB_DRIVER")
    DB_SERVER = os.getenv("DB_SERVER")
    DB_DATABASE = os.getenv("DB_DATABASE")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_TRUST_CERT = os.getenv("DB_TRUST_CERT", "yes")

    CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
    CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "pos_faq")
    CHROMA_TOMBSTONE_DB = os.getenv("CHROMA_TOMBSTONE_DB")

    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")

    MCP_BASE_URL = os.getenv("MCP_BASE_URL")
    MCP_API_KEY = os.getenv("MCP_API_KEY")
    MCP_TIMEOUT_SEC = int(os.getenv("MCP_TIMEOUT_SEC", "10"))

settings = Settings()
