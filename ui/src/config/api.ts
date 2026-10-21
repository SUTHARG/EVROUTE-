/**
 * Centralized API configuration for Route.ev frontend.
 *
 * Configurable via NEXT_PUBLIC_API_BASE_URL (or NEXT_PUBLIC_API_URL).
 * Falls back safely to standard local development address http://127.0.0.1:8000.
 */

export const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";
