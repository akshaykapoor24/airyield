from sqlalchemy import create_engine
from app.database import Base
from app.models import *  # noqa: F401,F403  (registers every model on Base.metadata)
from app.config import settings

engine = create_engine(settings.DATABASE_URL_SYNC)
Base.metadata.create_all(engine)
print(f"{len(Base.metadata.tables)} tables:", sorted(Base.metadata.tables))