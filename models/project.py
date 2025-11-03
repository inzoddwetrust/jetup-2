from sqlalchemy import Column, Integer, String, Float, Text, UniqueConstraint, Index
from models.base import Base


class Project(Base):
    __tablename__ = 'projects'

    # Автоинкрементный ID для внутреннего использования
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Бизнес-ключи
    projectID = Column(Integer, nullable=False, index=True)
    lang = Column(String, nullable=False)

    # Остальные поля
    projectName = Column(String, nullable=False)
    projectTitle = Column(String)
    fullText = Column(Text)
    status = Column(String)
    rate = Column(Float)
    linkImage = Column(String)
    linkPres = Column(String)
    linkVideo = Column(String)
    docsFolder = Column(String)

    # Индексы и ограничения
    __table_args__ = (
        UniqueConstraint('projectID', 'lang', name='_project_lang_uc'),
        # Composite index for get_project_by_id queries (projectID, lang, status)
        Index('ix_project_id_lang_status', 'projectID', 'lang', 'status'),
        # Composite index for sorted project list queries (status, rate)
        Index('ix_project_status_rate', 'status', 'rate'),
    )