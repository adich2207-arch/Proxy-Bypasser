import os
import logging
from sqlalchemy import create_engine, Column, String, LargeBinary, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

Base = declarative_base()


class TelegramSession(Base):
    """Database model for storing Telegram session"""
    __tablename__ = 'telegram_sessions'
    
    session_name = Column(String(255), primary_key=True)
    session_data = Column(Text, nullable=False)


class DatabaseSessionStore:
    """Handles storing and retrieving Telegram sessions from database"""
    
    def __init__(self, database_url):
        """
        Initialize database connection
        
        Args:
            database_url: PostgreSQL connection URL
        """
        try:
            # Create engine with connection pooling disabled for serverless
            self.engine = create_engine(
                database_url,
                poolclass=NullPool,
                echo=False
            )
            
            # Create tables if they don't exist
            Base.metadata.create_all(self.engine)
            
            # Create session factory
            Session = sessionmaker(bind=self.engine)
            self.db_session = Session()
            
            logger.info("Database session store initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    def save_session(self, session_name, session_string):
        """
        Save Telegram session to database
        
        Args:
            session_name: Name/identifier for the session
            session_string: Serialized session string from Telethon
        """
        try:
            # Check if session already exists
            existing = self.db_session.query(TelegramSession).filter_by(
                session_name=session_name
            ).first()
            
            if existing:
                # Update existing session
                existing.session_data = session_string
                logger.info(f"Updated existing session: {session_name}")
            else:
                # Create new session
                new_session = TelegramSession(
                    session_name=session_name,
                    session_data=session_string
                )
                self.db_session.add(new_session)
                logger.info(f"Created new session: {session_name}")
            
            self.db_session.commit()
            logger.info(f"Session saved successfully: {session_name}")
            
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            self.db_session.rollback()
            raise
    
    def load_session(self, session_name):
        """
        Load Telegram session from database
        
        Args:
            session_name: Name/identifier for the session
            
        Returns:
            Session string if found, None otherwise
        """
        try:
            session = self.db_session.query(TelegramSession).filter_by(
                session_name=session_name
            ).first()
            
            if session:
                logger.info(f"Loaded session from database: {session_name}")
                return session.session_data
            else:
                logger.info(f"No session found in database: {session_name}")
                return None
                
        except Exception as e:
            logger.error(f"Error loading session: {e}")
            return None
    
    def delete_session(self, session_name):
        """
        Delete session from database
        
        Args:
            session_name: Name/identifier for the session
        """
        try:
            session = self.db_session.query(TelegramSession).filter_by(
                session_name=session_name
            ).first()
            
            if session:
                self.db_session.delete(session)
                self.db_session.commit()
                logger.info(f"Deleted session: {session_name}")
            else:
                logger.warning(f"Session not found for deletion: {session_name}")
                
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            self.db_session.rollback()
            raise
    
    def close(self):
        """Close database connection"""
        try:
            self.db_session.close()
            self.engine.dispose()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database: {e}")
