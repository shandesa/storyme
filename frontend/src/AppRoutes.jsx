/**
 * AppRoutes — the single source of routing truth for StoryMe.
 *
 * Flow:
 *   /            → LoginPage    (mobile + OTP or password)
 *   /otp         → OtpPage     (enter + verify 6-digit code)
 *   /register    → RegisterPage (new users: create password)
 *   /home        → HomePage    (story select → preview → PDF download)
 *
 * Session strategy: Option C (no persistence).
 * Refreshing /home returns to login — acceptable for MVP demo.
 * To add persistence later, wrap <HomePage /> in a <ProtectedRoute>
 * that checks sessionStorage/localStorage for a user token.
 */

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import LoginPage    from "@/pages/LoginPage";
import OtpPage      from "@/pages/OtpPage";
import RegisterPage from "@/pages/RegisterPage";
import HomePage     from "@/pages/HomePage";

export default function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/"         element={<LoginPage />} />
        <Route path="/otp"      element={<OtpPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/home"     element={<HomePage />} />

        {/* Catch-all: redirect unknown paths to login */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
