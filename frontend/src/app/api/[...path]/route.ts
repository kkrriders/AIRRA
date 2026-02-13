/**
 * Next.js API Route Proxy
 *
 * Proxies all requests to the backend API while keeping the API key server-side only.
 * This prevents exposing NEXT_PUBLIC_API_KEY to the browser.
 *
 * Features:
 * - Request ID tracing for distributed debugging
 * - Exponential backoff retry for transient failures (502/503/504)
 * - Error handling with proper status code forwarding
 *
 * Usage: Frontend makes requests to /api/* instead of direct backend calls
 */
import { NextRequest, NextResponse } from 'next/server';

const BACKEND_API_URL = process.env.BACKEND_API_URL || 'http://localhost:8000';
const BACKEND_API_KEY = process.env.BACKEND_API_KEY || process.env.NEXT_PUBLIC_API_KEY;

// Retry configuration
const MAX_RETRIES = 3;
const RETRY_DELAYS = [100, 500, 2000]; // ms
const RETRY_STATUS_CODES = [502, 503, 504]; // Transient errors to retry

/**
 * Generate a unique request ID for tracing
 */
function generateRequestId(): string {
  return `req_${Date.now()}_${Math.random().toString(36).substring(7)}`;
}

export async function GET(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return handleRequest(request, params, 'GET');
}

export async function POST(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return handleRequest(request, params, 'POST');
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return handleRequest(request, params, 'PATCH');
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return handleRequest(request, params, 'DELETE');
}

async function handleRequest(
  request: NextRequest,
  params: { path: string[] },
  method: string
) {
  const path = params.path.join('/');
  const searchParams = request.nextUrl.searchParams.toString();
  const url = `${BACKEND_API_URL}/api/v1/${path}${searchParams ? `?${searchParams}` : ''}`;

  // Generate request ID for tracing
  const requestId = generateRequestId();

  try {
    // Build headers
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      'X-Request-ID': requestId, // For distributed tracing
    };

    // Add API key if not the acknowledge endpoint (which uses token-based auth)
    if (!path.includes('acknowledge') && BACKEND_API_KEY) {
      headers['X-API-Key'] = BACKEND_API_KEY;
    }

    // Get request body for POST/PATCH
    let body: string | undefined;
    if (method === 'POST' || method === 'PATCH') {
      body = await request.text();
    }

    // Retry logic with exponential backoff
    let lastError: Error | null = null;
    let response: Response | null = null;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        // Forward request to backend
        response = await fetch(url, {
          method,
          headers,
          body,
        });

        // Check if we should retry based on status code
        if (attempt < MAX_RETRIES && RETRY_STATUS_CODES.includes(response.status)) {
          const delay = RETRY_DELAYS[attempt];
          if (process.env.NODE_ENV !== 'production') {
            console.warn(`[API Proxy] Retry attempt ${attempt + 1}/${MAX_RETRIES} after ${delay}ms (status: ${response.status})`);
          }
          await new Promise(resolve => setTimeout(resolve, delay));
          continue; // Retry
        }

        // Success or non-retriable error - break loop
        break;
      } catch (fetchError) {
        lastError = fetchError instanceof Error ? fetchError : new Error('Unknown fetch error');

        // Retry on network errors (except on last attempt)
        if (attempt < MAX_RETRIES) {
          const delay = RETRY_DELAYS[attempt];
          if (process.env.NODE_ENV !== 'production') {
            console.warn(`[API Proxy] Network error, retry ${attempt + 1}/${MAX_RETRIES} after ${delay}ms: ${lastError.message}`);
          }
          await new Promise(resolve => setTimeout(resolve, delay));
          continue; // Retry
        }

        // Last attempt failed - throw
        throw lastError;
      }
    }

    // If we exhausted retries and still have no response, throw the last error
    if (!response) {
      throw lastError || new Error('Max retries exceeded with no response');
    }

    // Parse response body (try JSON first, fall back to text)
    const contentType = response.headers.get('content-type');
    let data: any;

    if (contentType?.includes('application/json')) {
      try {
        data = await response.json();
      } catch (parseError) {
        // JSON parse failed, try text
        const text = await response.text();
        data = {
          error: 'Invalid JSON response from backend',
          rawResponse: text.substring(0, 500), // Limit size
        };
      }
    } else {
      // Non-JSON response, get text
      const text = await response.text();
      data = {
        message: text,
        contentType: contentType || 'unknown',
      };
    }

    // Forward the original status code from backend (don't always return 500)
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Content-Type': 'application/json',
        'X-Request-ID': requestId, // Return request ID for client debugging
      },
    });
  } catch (error) {
    // Network error or fetch failure (not a backend error)
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';

    // Structured logging for production (only in non-production for console.error)
    if (process.env.NODE_ENV === 'production') {
      // In production, use structured logging service (e.g., Sentry, LogRocket)
      // Example: Sentry.captureException(error, { extra: { url, method, requestId } });
    } else {
      // Development: console logging is acceptable
      console.error('[API Proxy] Network error:', {
        requestId,
        url,
        method,
        error: errorMessage,
        timestamp: new Date().toISOString(),
      });
    }

    // Return 502 Bad Gateway for network errors (proxy couldn't reach backend)
    return NextResponse.json(
      {
        error: 'Backend unreachable',
        message: `Failed to connect to backend after ${MAX_RETRIES} retries: ${errorMessage}`,
        requestId, // Include request ID for debugging
        backend: process.env.NODE_ENV === 'production' ? undefined : BACKEND_API_URL, // Hide backend URL in production
      },
      {
        status: 502,
        headers: {
          'X-Request-ID': requestId,
        },
      }
    );
  }
}
