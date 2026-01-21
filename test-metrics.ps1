# Quick Test Script for Metrics
# This script helps you test all the metrics

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Concert Ticket Booking - Metrics Test" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Check if services are running
Write-Host "[1/5] Checking if services are running..." -ForegroundColor Yellow
$services = docker-compose ps --services --filter "status=running"
if ($services -match "backend") {
    Write-Host "[OK] Backend is running" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Backend is not running. Please run: docker-compose up -d" -ForegroundColor Red
    exit 1
}

Start-Sleep -Seconds 2

# Setup event
Write-Host "`n[2/5] Setting up event with 100 tickets..." -ForegroundColor Yellow
$setupResponse = Invoke-RestMethod -Uri "http://localhost:8000/setup" `
    -Method Post `
    -ContentType "application/json" `
    -Body '{"event_name": "Coldplay Concert - Jakarta", "total_tickets": 100}'

Write-Host "[OK] Event setup: $($setupResponse.event_name)" -ForegroundColor Green
Write-Host "  Total tickets: $($setupResponse.total_tickets)" -ForegroundColor Gray

Start-Sleep -Seconds 2

# Make some bookings
Write-Host "`n[3/5] Making sample bookings to generate metrics..." -ForegroundColor Yellow
$successCount = 0
$failCount = 0

for ($i = 1001; $i -le 1010; $i++) {
    try {
        $bookResponse = Invoke-RestMethod -Uri "http://localhost:8000/book" `
            -Method Post `
            -ContentType "application/json" `
            -Body "{`"user_id`": $i, `"event_id`": 1}"
        $successCount++
        Write-Host "  [OK] Booked ticket for user $i" -ForegroundColor Green
    } catch {
        $failCount++
        Write-Host "  [FAIL] Failed for user $i" -ForegroundColor Red
    }
    Start-Sleep -Milliseconds 100
}

Write-Host "`nBooking results: $successCount success, $failCount failed" -ForegroundColor Cyan

Start-Sleep -Seconds 2

# Check status
Write-Host "`n[4/5] Checking current status..." -ForegroundColor Yellow
$status = Invoke-RestMethod -Uri "http://localhost:8000/status"
$event = $status.events[0]

Write-Host "[OK] Event: $($event.name)" -ForegroundColor Green
Write-Host "  Available tickets: $($event.available_tickets)" -ForegroundColor Gray
Write-Host "  Sold tickets: $($event.sold_tickets)" -ForegroundColor Gray
Write-Host "  Total bookings recorded: $($status.total_bookings_recorded)" -ForegroundColor Gray

Start-Sleep -Seconds 2

# Display metrics URLs
Write-Host "`n[5/5] Metrics are now available!" -ForegroundColor Yellow
Write-Host ""
Write-Host "VIEW METRICS AT:" -ForegroundColor Cyan
Write-Host "  -> Raw metrics:  http://localhost:8000/metrics" -ForegroundColor White
Write-Host "  -> Prometheus:   http://localhost:9090" -ForegroundColor White
Write-Host "  -> Grafana:      http://localhost:3000 (admin/admin)" -ForegroundColor White
Write-Host "  -> Frontend:     http://localhost:8080" -ForegroundColor White
Write-Host ""

Write-Host "KEY METRICS TO CHECK IN PROMETHEUS:" -ForegroundColor Cyan
Write-Host "  1. RPS:              rate(http_requests_total[1m])" -ForegroundColor Gray
Write-Host "  2. P95 Response:     histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))" -ForegroundColor Gray
Write-Host "  3. Error Rate:       sum(rate(http_requests_total{status=~'4..|5..'}[1m])) / sum(rate(http_requests_total[1m])) * 100" -ForegroundColor Gray
Write-Host "  4. CPU Usage:        backend_cpu_usage_percent" -ForegroundColor Gray
Write-Host "  5. DB Latency:       histogram_quantile(0.95, sum(rate(db_query_duration_seconds_bucket[5m])) by (le))" -ForegroundColor Gray
Write-Host ""

Write-Host "TO GENERATE LOAD (and trigger race conditions):" -ForegroundColor Cyan
Write-Host "  docker exec -it ticket-k6 k6 run /scripts/load-test.js" -ForegroundColor White
Write-Host ""

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "All metrics are ready!" -ForegroundColor Green
Write-Host "=====================================" -ForegroundColor Cyan
