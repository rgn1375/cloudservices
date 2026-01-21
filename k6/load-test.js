import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '10s', target: 10 },   // Ramp up to 10 users
    { duration: '30s', target: 50 },   // Ramp up to 50 users
    { duration: '30s', target: 100 },  // Ramp up to 100 users (RACE CONDITION!)
    { duration: '20s', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'], // 95% of requests should be below 500ms
  },
};

const BASE_URL = 'http://backend:8000';

export default function () {
  // Random user ID between 1000 and 9999
  const userId = Math.floor(Math.random() * 9000) + 1000;
  
  const payload = JSON.stringify({
    user_id: userId,
    event_id: 7,  // Final heavy load test
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
  };

  // Attempt to book a ticket
  const response = http.post(`${BASE_URL}/book`, payload, params);
  
  check(response, {
    'booking request completed': (r) => r.status === 200 || r.status === 400,
    'booking successful': (r) => r.status === 200,
  });

  sleep(0.1); // Small delay between requests
}
