from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    BACKEND_PORT: int = 8000
    FRONTEND_PORT: int = 3000
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Sign-in session cookie: days it lasts; 'lax' when the app and server are on one site (localhost, or
    # app.firm.co.uk + api.firm.co.uk), 'none' when on different sites (then https is needed: COOKIE_SECURE)
    SESSION_DAYS: int = 7
    COOKIE_SAMESITE: str = "lax"
    COOKIE_SECURE: bool = False

    # Database (PostgreSQL). On AWS RDS: the URL without a password, and the Secrets Manager secret RDS keeps it in
    DATABASE_URL: str = ""
    DATABASE_SECRET_ARN: str = ""

    # AWS S3 & Bedrock
    AWS_REGION: str = "us-east-1"
    # The AI may run in another region than the files (empty: the same as AWS_REGION)
    BEDROCK_REGION: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET_NAME: str = ""
    # Where uploads and built workbooks are kept: 'local' (data/storage, for a laptop) or 's3' (server)
    FILE_STORAGE: str = "local"

    # AI models
    BEDROCK_PRIMARY_MODEL: str = "deepseek.v3.2"
    COMPANIES_HOUSE_API_KEY: str = ""  # public register lookups (directors, shareholders over 25%)
    BEDROCK_REASONING_MODEL: str = "openai.gpt-oss-120b-1:0"
    # The assistant (chat panel): its model, and the one that answers when that one fails
    ASSISTANT_MODEL: str = "deepseek.v3.2"
    ASSISTANT_BACKUP_MODEL: str = "moonshotai.kimi-k2.5"
    # The assistant's law knowledge base (HMRC manuals, notices, legislation), kept in Postgres (pgvector). Embeddings
    # from AWS Bedrock in London: Amazon Titan Text Embeddings V2. Also possible: Cohere Embed v4
    # (cohere.embed-v4:0, needs AWS Marketplace) or Google ('gemini', needs GOOGLE_API_KEY). Changing the provider, model
    # or size means embedding every piece again (backend/scripts/kb_reembed.py).
    KB_EMBED_PROVIDER: str = "bedrock"
    KB_EMBED_MODEL: str = "amazon.titan-embed-text-v2:0"
    KB_EMBED_DIMS: int = 1024
    KB_EMBED_REGION: str = ""                    # the embedding model's region; empty: the chat model's (London)
    GOOGLE_API_KEY: str = ""
    # The test chat page (/chat): opened with this 4-digit code instead of a sign-in (empty: the page is off). It sees
    # the law and SOP knowledge only, never a client. A device is remembered for CHAT_DEVICE_DAYS; its AI spend stops
    # for the day at CHAT_DAILY_LIMIT_USD (US$, every device together)
    CHAT_PIN: str = ""
    CHAT_DEVICE_DAYS: int = 90
    CHAT_DAILY_LIMIT_USD: float = 5.0

    # Project Paths
    APP_DIR: Path = Path(__file__).resolve().parent.parent
    BACKEND_DIR: Path = APP_DIR.parent
    BASE_DIR: Path = BACKEND_DIR.parent
    DATA_DIR: Path = BASE_DIR / "data"

    # Self-Contained Master Template Path (Bundled inside backend/app/templates)
    TEMPLATE_PATH: Path = APP_DIR / "templates" / "master_workpapers_template.xlsx"
    # data/ (on this computer only, not in git): reference/ (templates, COA, SOPs, specs, law), clients/<name>/inputs
    # and /accountant, outputs/, archive/, and storage/ (what the app saves when FILE_STORAGE=local)
    REFERENCE_DIR: Path = DATA_DIR / "reference"
    LOCAL_STORAGE_DIR: Path = DATA_DIR / "storage"
    FALLBACK_TEMPLATE_PATH: Path = REFERENCE_DIR / "templates" / "Working Papers TEMPLATE v8 (COA dictionary).xlsx"
    COA_PATH: Path = REFERENCE_DIR / "coa" / "Account codes.xlsx"


    class Config:
        env_file = str(Path(__file__).resolve().parent.parent.parent / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
