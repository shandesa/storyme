/**
 * AppRoutes — single source of routing truth for StoryMe.
 *
 * Auth-protected routes are wrapped in <ProtectedRoute>.
 * ProtectedRoute validates the JWT session token on mount,
 * starts the inactivity timer, and shows a 30s warning before logout.
 *
 * Public routes (no auth required):
 *   /              → LoginPage
 *   /otp           → OtpPage
 *   /register      → RegisterPage
 *
 * Protected routes (require valid JWT in sessionStorage):
 *   /home          → HomePage
 *   /print-order   → PrintOrderPage
 *   /order-status/:orderId → OrderStatusPage
 *
 * Admin routes (auth inside the page via X-Admin-Key header):
 *   /admin/orders  → AdminOrdersPage
 */

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import ProtectedRoute   from "@/components/ProtectedRoute";
import LoginPage        from "@/pages/LoginPage";
import OtpPage          from "@/pages/OtpPage";
import RegisterPage     from "@/pages/RegisterPage";
import TermsPage        from "@/pages/TermsPage";
import HomePage         from "@/pages/HomePage";
import PrintOrderPage   from "@/pages/PrintOrderPage";
import PaymentPage      from "@/pages/PaymentPage";
import OrderStatusPage  from "@/pages/OrderStatusPage";
import AdminOrdersPage  from "@/pages/AdminOrdersPage";
import AdminFaceTestPage from "@/pages/AdminFaceTestPage";
import KidProfilesPage  from "@/pages/KidProfilesPage";

export default function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        {/* ── Public ── */}
        <Route path="/"         element={<LoginPage />} />
        <Route path="/otp"      element={<OtpPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/terms"    element={<TermsPage />} />

        {/* ── Protected (require valid session token) ── */}
        <Route path="/home" element={
          <ProtectedRoute><HomePage /></ProtectedRoute>
        } />
        <Route path="/print-order" element={
          <ProtectedRoute><PrintOrderPage /></ProtectedRoute>
        } />
        <Route path="/payment" element={
          <ProtectedRoute><PaymentPage /></ProtectedRoute>
        } />
        <Route path="/profiles" element={
          <ProtectedRoute><KidProfilesPage /></ProtectedRoute>
        } />
        <Route path="/order-status/:orderId" element={
          <ProtectedRoute><OrderStatusPage /></ProtectedRoute>
        } />

        {/* ── Admin (internal auth via X-Admin-Key) ── */}
        <Route path="/admin/orders"    element={<AdminOrdersPage />} />
        <Route path="/admin/face-test" element={<AdminFaceTestPage />} />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
