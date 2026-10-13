import psycopg2
from psycopg2 import pool, extras, OperationalError
from backend.config import DB_CONFIG
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DatabaseConnection:
    _instance = None
    _pool = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseConnection, cls).__new__(cls)
            cls._initialize_pool()
        return cls._instance

    @classmethod
    def _initialize_pool(cls):
        try:
            # SSL configuration for database connection
            db_config = DB_CONFIG.copy()
            if 'sslmode' in db_config:
                del db_config['sslmode']
            cls._pool = psycopg2.pool.ThreadedConnectionPool(
                1,
                20,
                **db_config
            )
            logger.info("PostgreSQL connection pool created successfully")
        except Exception as e:
            logger.error(f"Error creating connection pool: {e}")
            raise

    def get_connection(self):
        """Get a connection from the pool with retry logic and health check"""
        max_retries = 3
        for attempt in range(max_retries):
            conn = None
            try:
                conn = self._pool.getconn()
                # Properly test the connection with a simple query
                cursor = conn.cursor()
                cursor.execute('SELECT 1')
                cursor.close()
                return conn
            except (OperationalError, Exception) as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                # Return bad connection to pool with close flag
                if conn:
                    try:
                        self._pool.putconn(conn, close=True)
                    except:
                        pass
                if attempt < max_retries - 1:
                    # Reinitialize the pool if connection fails
                    try:
                        self._initialize_pool()
                    except:
                        pass
                else:
                    logger.error(f"Failed to get connection after {max_retries} attempts")
                    raise

    def return_connection(self, conn, close=False):
        """Return connection to the pool or close it if it's bad"""
        try:
            self._pool.putconn(conn, close=close)
        except Exception as e:
            logger.error(f"Error returning connection: {e}")

    @contextmanager
    def transaction(self):
        """Yield a PostgreSQL cursor and commit or roll back the whole unit."""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
        close_conn = False
        try:
            yield cursor
            conn.commit()
        except (OperationalError, psycopg2.InterfaceError):
            close_conn = True
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            self.return_connection(conn, close=close_conn)

    def execute_query(self, query, params=None):
        conn = None
        cursor = None
        close_conn = False
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            conn.commit()
            last_id = cursor.lastrowid if hasattr(cursor, 'lastrowid') else None
            return last_id
        except (OperationalError, psycopg2.InterfaceError) as e:
            close_conn = True
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            logger.error(f"Database connection error: {str(e)}")
            raise e
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {str(e)}")
            raise e
        finally:
            if cursor:
                cursor.close()
            if conn:
                self.return_connection(conn, close=close_conn)

    def execute_returning(self, query, params=None):
        """Execute a write query with RETURNING and commit it atomically."""
        conn = None
        cursor = None
        close_conn = False
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute(query, params) if params else cursor.execute(query)
            result = cursor.fetchone()
            conn.commit()
            return result
        except (OperationalError, psycopg2.InterfaceError) as e:
            close_conn = True
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"Database connection error: {str(e)}")
            raise
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {str(e)}")
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                self.return_connection(conn, close=close_conn)

    def fetch_all(self, query, params=None):
        conn = None
        cursor = None
        close_conn = False
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            results = cursor.fetchall()
            return results
        except (OperationalError, psycopg2.InterfaceError) as e:
            close_conn = True
            logger.error(f"Error fetching data (connection issue): {e}")
            raise e
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            raise e
        finally:
            if cursor:
                cursor.close()
            if conn:
                self.return_connection(conn, close=close_conn)

    def fetch_one(self, query, params=None):
        conn = None
        cursor = None
        close_conn = False
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            result = cursor.fetchone()
            return result
        except (OperationalError, psycopg2.InterfaceError) as e:
            close_conn = True
            logger.error(f"Error fetching data (connection issue): {e}")
            raise e
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            raise e
        finally:
            if cursor:
                cursor.close()
            if conn:
                self.return_connection(conn, close=close_conn)

# Example usage:
if __name__ == "__main__":
    try:
        db = DatabaseConnection()
        # Example SELECT query
        results = db.fetch_all("SELECT * FROM waste_sourcing LIMIT 5")
        print("Query results:", results)
        # Example INSERT query
        insert_query = """
        INSERT INTO waste_sourcing 
        (collection_date, source_type, waste_type, weight) 
        VALUES (%s, %s, %s, %s)
        """
        params = ('2024-03-20', 'Restaurant', 'Food Waste', 50.5)
        affected_rows = db.execute_query(insert_query, params)
        print(f"Inserted {affected_rows} rows")
    except Exception as e:
        print(f"Database error: {e}") 
