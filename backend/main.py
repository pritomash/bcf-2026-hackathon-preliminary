import gen_ai
from db_reflector import fetch_dynamic_schema
import psycopg2
from dotenv.main import logger
import logging
from psycopg2 import pool
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import JSONResponse
from psycopg2 import OperationalError
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel
from contextlib import asynccontextmanager
from fastapi import status
from typing import Generator
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    PORT: int = 8080
    GEMINI_API_KEY: str
    APP_DEBUG: bool
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()

class DatabaseManager:
    def __init__(self):
        self.db_pool : pool.ThreadedConnectionPool | None = None
    def initialize_pool(self):
        try:
            self.db_pool = pool.ThreadedConnectionPool(
                minconn=5,
                maxconn=10,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                database=settings.DB_NAME
            )
            logger.info("Database connection pool initialized successfully.")
        except OperationalError as e:
            logger.error(f"Error initializing database connection pool: {e}")
            self.db_pool = None
            raise RuntimeError("Failed to initialize database connection pool") from e
    def close_pool(self):
        if self.db_pool:
            self.db_pool.closeall()
            logger.info("Database connection pool closed.")

db_manager = DatabaseManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    db_manager.initialize_pool()
    yield
    db_manager.close_pool()

app = FastAPI(lifespan=lifespan)

# 5. FastAPI Dependency for Database Connections
def get_db() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Dependency that yields a database connection from the pool.
    Ensures rollback on error and safely returns connection to pool.
    """
    if not db_manager.db_pool:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Database pool is unavailable"
        )
        
    conn = db_manager.db_pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database transaction error, rolled back: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Database execution error"
        )
    finally:
        db_manager.db_pool.putconn(conn)

@app.get("/health")
def health_check():
    if not db_manager.db_pool:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "database": "not initialized"}
        )
    try:
        conn = db_manager.db_pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        db_manager.db_pool.putconn(conn)
        return JSONResponse(content={"status": "ok", "database": "connected"})
    except OperationalError as e:
        logger.error(f"Database health check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "database": "connection failed"}
        )
    return JSONResponse(content=status)

class QueryRequest(BaseModel):
    question: str
    llm: str

@app.post("/query")
def query_endpoint(body: QueryRequest, db: psycopg2.extensions.connection = Depends(get_db)):
    question = body.question
    llm = body.llm
    
    current_schema = fetch_dynamic_schema(db)
    #logger.info(f"Reflected database schema: {current_schema}")

    try:
        sql_query = gen_ai.init_genai_conversation(question, llm, current_schema)
        logger.info(f"Generated SQL query: {sql_query}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM compilation failed: {str(e)}")
    
    # 3. Execute query on PostgreSQL
    try:
        with db.cursor() as cur:
            cur.execute(sql_query)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchall() if cur.description else []
    except Exception as e:
        logger.error(f"Database execution rejected SQL: {e}")
        raise HTTPException(status_code=400, detail=f"SQL syntax execution error: {str(e)}")

    # 4. Standardized Output Format Detection Evaluation
    row_count = len(rows)
    col_count = len(columns)
    
    if row_count == 1 and col_count == 1:
        result_type = "scalar"
    elif row_count == 1 and col_count > 1:
        result_type = "record"
    else:
        result_type = "table"

    # Sanitize complex formats (like Decimals, dates) into clean primitives
    processed_rows = []
    for row in rows:
        processed_rows.append([
            float(val) if isinstance(val, (int, float)) and not isinstance(val, bool)
            else str(val) if val is not None else None
            for val in row
        ])

    return {
        "question": question,
        "llm": llm,
        "result_type": result_type,
        "columns": columns,
        "rows": processed_rows,
        "meta": {
            "row_count": row_count
        }
    }

# Configure CORS - in production, replace "*" with specific origins
allowed_origins = ["*"] if settings.APP_DEBUG else ["http://localhost:8000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
