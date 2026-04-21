/**
 * AppRoutes — single source of routing truth for StoryMe.
 *
 * Flow:
 *   /              → LoginPage
 *   /otp           → OtpPage
 *   /register      → RegisterPage
 *   /home          → HomePage     (story select → preview → PDF → print options)
 *   /print-order   → PrintOrderPage   (NEW — print product selection + delivery)
 *   /order-status/:orderId → OrderStatusPage (NEW — confirmation + tracking)
 *   /admin/orders  → AdminOrdersPage  (NEW — internal admin dashboard)
 *
 * State between pages is passed via React Router navigate state.
 * Nothing is stored in localStorage/sessionStorage for the generation flow.
 */

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import LoginPage      from "@/pages/LoginPage";
import OtpPage        from "@/pages/OtpPage";
import RegisterPage   from "@/pages/RegisterPage";
import HomePage       from "@/pages/HomePage";
import PrintOrderPage from "@/pages/PrintOrderPage";
import OrderStatusPage from "@/pages/OrderStatusPage";
import AdminOrdersPage from "@/pages/AdminOrdersPage";

export default function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Auth */}
        <Route path="/"         element={<LoginPage />} />
        <Route path="/otp"      element={<OtpPage />} />
        <Route path="/register" element={<RegisterPage />} />

        {/* Main generation flow */}
        <Route path="/home"     element={<HomePage />} />

        {/* Print ordering — entered from HomePage COMPLETE step */}
        <Route path="/print-order"              element={<PrintOrderPage />} />
        <Route path="/order-status/:orderId"    element={<OrderStatusPage />} />

        {/* Admin — protected by X-Admin-Key, no route-level auth guard needed */}
        <Route path="/admin/orders"             element={<AdminOrdersPage />} />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
