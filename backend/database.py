from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from config import DATABASE_URL

# Create the async engine
engine = create_async_engine(DATABASE_URL, echo=False)

# Create the async session factory
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Declarative base for models
Base = declarative_base()

# Dependency for FastAPI
async def get_db():
    async with async_session_factory() as session:
        yield session
