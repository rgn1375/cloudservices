from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram, Gauge, Summary
import mysql.connector
from mysql.connector import Error
import os
import time
import psutil
import threading

app = FastAPI(title="Concert Ticket Booking System")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CPU monitoring - track process CPU times for accurate container metrics
_cpu_value = 0.0
_cpu_lock = threading.Lock()
_process = psutil.Process()

def cpu_monitor_thread():
    """Background thread to calculate CPU usage from process times"""
    global _cpu_value
    
    # Get initial CPU times
    prev_times = _process.cpu_times()
    prev_time = time.time()
    
    while True:
        try:
            time.sleep(0.5)  # Sample more frequently
            
            # Get current CPU times
            curr_times = _process.cpu_times()
            curr_time = time.time()
            
            # Calculate CPU usage as percentage of elapsed time
            elapsed = curr_time - prev_time
            if elapsed > 0:
                # Total CPU time used (user + system)
                cpu_used = (curr_times.user - prev_times.user) + (curr_times.system - prev_times.system)
                # Convert to percentage of a single core
                # This gives more meaningful numbers for a web server
                cpu_percent = (cpu_used / elapsed) * 100
                
                with _cpu_lock:
                    _cpu_value = round(cpu_percent, 2)
            
            prev_times = curr_times
            prev_time = curr_time
            
        except Exception as e:
            print(f"CPU monitor error: {e}")

# Start CPU monitoring thread
_cpu_thread = threading.Thread(target=cpu_monitor_thread, daemon=True)
_cpu_thread.start()

# Middleware to update system metrics on each request
@app.middleware("http")
async def metrics_middleware(request, call_next):
    global _cpu_value
    
    # Update system metrics
    try:
        with _cpu_lock:
            cpu_usage_percent.set(_cpu_value)
        
        memory_info = _process.memory_info()
        memory_usage_bytes.set(memory_info.rss)
    except Exception as e:
        print(f"Metrics error: {e}")
    
    response = await call_next(request)
    return response

# Custom Prometheus metrics
db_query_duration = Histogram(
    'db_query_duration_seconds',
    'Database query duration in seconds',
    ['operation', 'table']
)

db_connection_errors = Counter(
    'db_connection_errors_total',
    'Total number of database connection errors'
)

booking_attempts = Counter(
    'booking_attempts_total',
    'Total booking attempts',
    ['status']  # success, failed, sold_out
)

tickets_remaining = Gauge(
    'tickets_remaining',
    'Number of tickets remaining',
    ['event_id']
)

cpu_usage_percent = Gauge(
    'backend_cpu_usage_percent',
    'Backend CPU usage percentage'
)

memory_usage_bytes = Gauge(
    'backend_memory_usage_bytes',
    'Backend memory usage in bytes'
)

# Prometheus instrumentation with detailed metrics
instrumentator = Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
)

instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'mariadb'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', 'root'),
    'database': os.getenv('DB_NAME', 'ticketdb')
}

def get_db_connection():
    """Create and return a database connection"""
    max_retries = 5
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            start_time = time.time()
            connection = mysql.connector.connect(**DB_CONFIG)
            duration = time.time() - start_time
            db_query_duration.labels(operation='connect', table='none').observe(duration)
            return connection
        except Error as e:
            db_connection_errors.inc()
            if attempt < max_retries - 1:
                print(f"Database connection failed (attempt {attempt + 1}/{max_retries}): {e}")
                time.sleep(retry_delay)
            else:
                raise Exception(f"Failed to connect to database after {max_retries} attempts: {e}")

def init_database():
    """Initialize database and create tables if they don't exist"""
    try:
        # Connect without specifying database first
        temp_config = DB_CONFIG.copy()
        db_name = temp_config.pop('database')
        
        connection = mysql.connector.connect(**temp_config)
        cursor = connection.cursor()
        
        # Create database if not exists
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
        cursor.execute(f"USE {db_name}")
        
        # Create events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                total_tickets INT NOT NULL,
                available_tickets INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create bookings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                event_id INT NOT NULL,
                booked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_id) REFERENCES events(id)
            )
        """)
        
        connection.commit()
        cursor.close()
        connection.close()
        print("Database initialized successfully")
    except Error as e:
        print(f"Error initializing database: {e}")
        raise

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_database()

# Request models
class SetupRequest(BaseModel):
    event_name: str = "Coldplay Concert - Jakarta"
    total_tickets: int = 100

class BookRequest(BaseModel):
    user_id: int
    event_id: int = 1

# Endpoints
@app.get("/")
async def root():
    return {
        "message": "Concert Ticket Booking System API",
        "version": "1.0",
        "endpoints": {
            "setup": "POST /setup",
            "book": "POST /book",
            "status": "GET /status",
            "metrics": "GET /metrics"
        }
    }

@app.post("/setup")
async def setup(request: SetupRequest):
    """
    Reset database and seed a concert event with limited tickets
    """
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Clear existing data
        start_time = time.time()
        cursor.execute("DELETE FROM bookings")
        db_query_duration.labels(operation='delete', table='bookings').observe(time.time() - start_time)
        
        start_time = time.time()
        cursor.execute("DELETE FROM events")
        db_query_duration.labels(operation='delete', table='events').observe(time.time() - start_time)
        
        # Insert new event
        start_time = time.time()
        cursor.execute("""
            INSERT INTO events (name, total_tickets, available_tickets)
            VALUES (%s, %s, %s)
        """, (request.event_name, request.total_tickets, request.total_tickets))
        db_query_duration.labels(operation='insert', table='events').observe(time.time() - start_time)
        
        connection.commit()
        event_id = cursor.lastrowid
        
        # Update gauge
        tickets_remaining.labels(event_id=event_id).set(request.total_tickets)
        
        cursor.close()
        connection.close()
        
        return {
            "message": "Event setup successful",
            "event_id": event_id,
            "event_name": request.event_name,
            "total_tickets": request.total_tickets
        }
    except Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/book")
async def book_ticket(request: BookRequest):
    """
    Book a ticket - NAIVE implementation (demonstrates race conditions)
    This intentionally lacks proper locking/transactions to show overselling
    """
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        start_time = time.time()
        cursor.execute("""
            SELECT available_tickets FROM events WHERE id = %s
        """, (request.event_id,))
        db_query_duration.labels(operation='select', table='events').observe(time.time() - start_time)
        
        event = cursor.fetchone()
        
        if not event:
            booking_attempts.labels(status='failed').inc()
            cursor.close()
            connection.close()
            raise HTTPException(status_code=404, detail="Event not found")
        
        if event['available_tickets'] <= 0:
            booking_attempts.labels(status='sold_out').inc()
            cursor.close()
            connection.close()
            raise HTTPException(status_code=400, detail="Sold out!")
        
        time.sleep(0.01)
        
        start_time = time.time()
        cursor.execute("""
            UPDATE events 
            SET available_tickets = available_tickets - 1 
            WHERE id = %s
        """, (request.event_id,))
        db_query_duration.labels(operation='update', table='events').observe(time.time() - start_time)
        
        start_time = time.time()
        cursor.execute("""
            INSERT INTO bookings (user_id, event_id)
            VALUES (%s, %s)
        """, (request.user_id, request.event_id))
        db_query_duration.labels(operation='insert', table='bookings').observe(time.time() - start_time)
        
        connection.commit()
        
        start_time = time.time()
        cursor.execute("SELECT available_tickets FROM events WHERE id = %s", (request.event_id,))
        db_query_duration.labels(operation='select', table='events').observe(time.time() - start_time)
        updated_event = cursor.fetchone()
        
        # Update metrics
        booking_attempts.labels(status='success').inc()
        tickets_remaining.labels(event_id=request.event_id).set(updated_event['available_tickets'])
        
        cursor.close()
        connection.close()
        
        return {
            "message": "Ticket booked successfully!",
            "user_id": request.user_id,
            "event_id": request.event_id,
            "remaining_tickets": updated_event['available_tickets']
        }
    except HTTPException:
        raise
    except Error as e:
        booking_attempts.labels(status='failed').inc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/status")
async def get_status():
    """
    Get current ticket status for all events
    """
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        start_time = time.time()
        cursor.execute("""
            SELECT id, name, total_tickets, available_tickets,
                   (total_tickets - available_tickets) as sold_tickets
            FROM events
        """)
        db_query_duration.labels(operation='select', table='events').observe(time.time() - start_time)
        
        events = cursor.fetchall()
        
        # Also get total bookings count
        start_time = time.time()
        cursor.execute("SELECT COUNT(*) as total_bookings FROM bookings")
        db_query_duration.labels(operation='select', table='bookings').observe(time.time() - start_time)
        bookings_result = cursor.fetchone()
        
        # Update gauge for each event
        for event in events:
            tickets_remaining.labels(event_id=event['id']).set(event['available_tickets'])
        
        cursor.close()
        connection.close()
        
        return {
            "events": events,
            "total_bookings_recorded": bookings_result['total_bookings']
        }
    except Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        connection = get_db_connection()
        connection.close()
        return {"status": "healthy", "database": "connected"}
    except:
        return {"status": "unhealthy", "database": "disconnected"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
