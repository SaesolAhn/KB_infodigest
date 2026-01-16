"""
Database Service for InfoDigest Bot.
Handles MongoDB operations for storing and retrieving digest logs.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any

from pymongo import MongoClient, DESCENDING
from pymongo.errors import ConnectionFailure, OperationFailure

from models.schemas import DigestLog, ContentType


class DatabaseError(Exception):
    """Raised when database operations fail."""
    pass


class DatabaseService:
    """
    Service for MongoDB operations.
    Handles saving and retrieving digest logs.
    """
    
    def __init__(
        self,
        uri: str = "mongodb://localhost:27017",
        database: str = "infodigest",
        collection: str = "digest_logs"
    ):
        """
        Initialize database connection.
        
        Args:
            uri: MongoDB connection URI
            database: Database name
            collection: Collection name for digest logs
        """
        self.uri = uri
        self.database_name = database
        self.collection_name = collection
        self._client: Optional[MongoClient] = None
        self._db = None
        self._collection = None
    
    def connect(self) -> None:
        """
        Establish database connection.
        
        Raises:
            DatabaseError: If connection fails
        """
        try:
            self._client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
            # Test connection
            self._client.admin.command('ping')
            self._db = self._client[self.database_name]
            self._collection = self._db[self.collection_name]
            
            # Create indexes for efficient querying
            self._collection.create_index([("timestamp", DESCENDING)])
            self._collection.create_index("url")
            self._collection.create_index("chat_id")
            
        except ConnectionFailure as e:
            raise DatabaseError(f"Failed to connect to MongoDB: {str(e)}")
        except Exception as e:
            raise DatabaseError(f"Database connection error: {str(e)}")
    
    def close(self) -> None:
        """Close database connection."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._collection = None
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
    
    @property
    def collection(self):
        """Get the collection, connecting if necessary."""
        if self._collection is None:
            self.connect()
        return self._collection
    
    def save_log(
        self,
        url: str,
        title: str,
        content_type: str,
        summary: str,
        raw_text_length: int = 0,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
        processing_time_ms: Optional[int] = None,
        error: Optional[str] = None
    ) -> str:
        """
        Save a digest log entry to the database.
        
        Args:
            url: The processed URL
            title: Content title
            content_type: Type of content ('youtube', 'web', 'pdf')
            summary: Generated summary
            raw_text_length: Length of extracted text
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            processing_time_ms: Processing time in milliseconds
            error: Error message if failed
            
        Returns:
            The inserted document ID as string
            
        Raises:
            DatabaseError: If save fails
        """
        try:
            log = DigestLog(
                url=url,
                title=title,
                content_type=ContentType.from_string(content_type),
                summary=summary,
                timestamp=datetime.utcnow(),
                raw_text_length=raw_text_length,
                chat_id=chat_id,
                message_id=message_id,
                processing_time_ms=processing_time_ms,
                error=error,
            )
            
            result = self.collection.insert_one(log.to_dict())
            return str(result.inserted_id)
            
        except OperationFailure as e:
            raise DatabaseError(f"Failed to save log: {str(e)}")
        except Exception as e:
            raise DatabaseError(f"Database error: {str(e)}")
    
    def get_logs(
        self,
        limit: int = 50,
        skip: int = 0,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[DigestLog]:
        """
        Retrieve digest logs from the database.
        
        Args:
            limit: Maximum number of logs to return
            skip: Number of logs to skip (for pagination)
            filters: Optional MongoDB filter criteria
            
        Returns:
            List of DigestLog objects
            
        Raises:
            DatabaseError: If query fails
        """
        try:
            query = filters or {}
            cursor = (
                self.collection
                .find(query)
                .sort("timestamp", DESCENDING)
                .skip(skip)
                .limit(limit)
            )
            
            logs = []
            for doc in cursor:
                try:
                    logs.append(DigestLog.from_dict(doc))
                except Exception:
                    # Skip malformed documents
                    continue
            
            return logs
            
        except OperationFailure as e:
            raise DatabaseError(f"Failed to retrieve logs: {str(e)}")
        except Exception as e:
            raise DatabaseError(f"Database error: {str(e)}")
    
    def get_log_by_url(self, url: str) -> Optional[DigestLog]:
        """
        Retrieve a log entry by URL.
        
        Args:
            url: The URL to search for
            
        Returns:
            DigestLog if found, None otherwise
        """
        try:
            doc = self.collection.find_one({"url": url})
            if doc:
                return DigestLog.from_dict(doc)
            return None
        except Exception:
            return None
    
    def get_logs_by_chat(
        self,
        chat_id: int,
        limit: int = 50
    ) -> List[DigestLog]:
        """
        Retrieve logs for a specific Telegram chat.
        
        Args:
            chat_id: Telegram chat ID
            limit: Maximum number of logs
            
        Returns:
            List of DigestLog objects
        """
        return self.get_logs(limit=limit, filters={"chat_id": chat_id})
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get summary statistics for the dashboard.
        
        Returns:
            Dictionary with statistics
        """
        try:
            total = self.collection.count_documents({})
            
            # Count by content type
            pipeline = [
                {"$group": {"_id": "$content_type", "count": {"$sum": 1}}}
            ]
            type_counts = {
                doc["_id"]: doc["count"] 
                for doc in self.collection.aggregate(pipeline)
            }
            
            # Count errors
            errors = self.collection.count_documents({"error": {"$ne": None}})
            
            return {
                "total_digests": total,
                "by_type": type_counts,
                "errors": errors,
                "success_rate": ((total - errors) / total * 100) if total > 0 else 100
            }
            
        except Exception:
            return {
                "total_digests": 0,
                "by_type": {},
                "errors": 0,
                "success_rate": 100
            }
    
    def delete_log(self, url: str) -> bool:
        """
        Delete a log entry by URL.
        
        Args:
            url: The URL of the log to delete
            
        Returns:
            True if deleted, False if not found
        """
        try:
            result = self.collection.delete_one({"url": url})
            return result.deleted_count > 0
        except Exception:
            return False

