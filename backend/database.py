import psycopg2
from psycopg2 import pool, extras, OperationalError
from backend.config import DB_CONFIG, DB_POOL_MAX
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DatabaseConnection:
    _instance = None
    _pool = None
    # Set by the web app to a function returning a JSON description of who is
    # acting (user, role, IP, request), or None outside a request. Audit
    # triggers read it from the app.audit_actor setting of each transaction.
    audit_actor = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseConnection, cls).__new__(cls)
            cls._initialize_pool()
        return cls._instance

    @classmethod
    def _initialize_pool(cls):
        try:
            cls._pool = psycopg2.pool.ThreadedConnectionPool(1, DB_POOL_MAX, **DB_CONFIG)
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
                # Health check that also tags this transaction with the actor
                # (transaction-local, so it never leaks to the next borrower).
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT set_config('app.audit_actor', %s, true)",
                    (self._current_audit_actor(),),
                )
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

    @classmethod
    def _current_audit_actor(cls):
        provider = cls.audit_actor
        if provider is None:
            return ''
        try:
            return provider() or ''
        except Exception:  # never block a query because the actor is unknown
            logger.exception("Could not describe the audit actor")
            return ''

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
        """Run a write and commit. The return value is not a row id (psycopg2
        has no lastrowid); use execute_returning with RETURNING for ids."""
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
