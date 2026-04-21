/**
 * OrderStatusPage.jsx
 * -------------------
 * Full-screen order confirmation and status page.
 *
 * Routes:
 *   /order-status/:orderId   (post-order confirmation)
 *
 * Two modes:
 *   1. Direct navigation from PrintOrderPage — order data in location.state
 *   2. Direct URL access — fetches order from /api/v2/orders/:orderId
 *
 * Shows:
 *   - Order ID (reference number)
 *   - Order status with visual timeline
 *   - Product details and price
 *   - Delivery address summary
 *   - Estimated delivery window
 *   - Navigation: Back to Home, Create Another Story
 */

import { useState, useEffect } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge }  from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  CheckCircle, Clock, Printer, Package, Truck, Home,
  ArrowLeft, RefreshCw, Loader2, MapPin, BookOpen,
} from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_V2      = `${BACKEND_URL}/api/v2`;

// ─── Status config ────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  pending: {
    label:       "Order Received",
    description: "Your order has been received. We'll confirm it shortly.",
    color:       "bg-blue-100 text-blue-700 border-blue-200",
    icon:        Clock,
    step:        1,
  },
  confirmed: {
    label:       "Order Confirmed",
    description: "Your order is confirmed and queued for printing.",
    color:       "bg-purple-100 text-purple-700 border-purple-200",
    icon:        CheckCircle,
    step:        2,
  },
  printing: {
    label:       "Printing in Progress",
    description: "Your storybook is being printed with love.",
    color:       "bg-amber-100 text-amber-700 border-amber-200",
    icon:        Printer,
    step:        3,
  },
  shipped: {
    label:       "Shipped",
    description: "Your storybook is on its way!",
    color:       "bg-cyan-100 text-cyan-700 border-cyan-200",
    icon:        Truck,
    step:        4,
  },
  delivered: {
    label:       "Delivered",
    description: "Your storybook has been delivered. Enjoy!",
    color:       "bg-emerald-100 text-emerald-700 border-emerald-200",
    icon:        Home,
    step:        5,
  },
  cancelled: {
    label:       "Cancelled",
    description: "This order has been cancelled.",
    color:       "bg-red-100 text-red-700 border-red-200",
    icon:        null,
    step:        0,
  },
};

const TIMELINE_STEPS = ["pending","confirmed","printing","shipped","delivered"];

function paise_to_display(paise) {
  if (!paise) return "";
  return `₹${paise / 100}`;
}

function formatDate(isoStr) {
  if (!isoStr) return null;
  try {
    return new Date(isoStr).toLocaleDateString("en-IN", {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return isoStr; }
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function OrderStatusPage() {
  const { orderId }   = useParams();
  const navigate      = useNavigate();
  const location      = useLocation();

  const [order,   setOrder]   = useState(location.state?.order || null);
  const [loading, setLoading] = useState(!order);
  const [error,   setError]   = useState(null);

  const childName = location.state?.childName || order?.child_name || "Your Child";

  // ── Fetch if not in navigation state ──────────────────────────────────────

  useEffect(() => {
    if (order) return;
    if (!orderId) { setError("No order ID provided."); return; }

    setLoading(true);
    axios.get(`${API_V2}/orders/${orderId}`)
      .then((res) => setOrder(res.data))
      .catch(() => setError("Order not found or could not be loaded."))
      .finally(() => setLoading(false));
  }, [orderId]);

  // ── Loading / error states ─────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-amber-50 to-emerald-50">
        <div className="text-center space-y-3">
          <Loader2 className="w-10 h-10 animate-spin text-emerald-500 mx-auto" />
          <p className="text-gray-500">Loading your order…</p>
        </div>
      </div>
    );
  }

  if (error || !order) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-amber-50 to-emerald-50 px-4">
        <Card className="max-w-md w-full shadow-lg">
          <CardContent className="pt-8 pb-8 text-center space-y-4">
            <p className="text-red-500 font-medium">{error || "Order not found."}</p>
            <Button onClick={() => navigate("/home")} variant="outline">
              <ArrowLeft className="mr-2 h-4 w-4" />Back to Home
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const status     = order.status || "pending";
  const statusConf = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  const StatusIcon = statusConf.icon || CheckCircle;
  const addr       = order.delivery_address || {};

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-white to-emerald-50 py-8 px-4">
      <div className="max-w-xl mx-auto">

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <Button variant="ghost" size="sm" onClick={() => navigate("/home")}
            className="text-gray-500 hover:text-gray-700 -ml-2">
            <ArrowLeft className="w-4 h-4 mr-1" />Home
          </Button>
          <h1 className="text-xl font-bold text-gray-900">Order Confirmation</h1>
        </div>

        {/* ── Success banner ── */}
        <Card className="shadow-md mb-5 border-emerald-200 bg-emerald-50">
          <CardContent className="pt-6 pb-5 text-center space-y-2">
            <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto">
              <CheckCircle className="w-9 h-9 text-emerald-600" />
            </div>
            <h2 className="text-xl font-bold text-emerald-800">
              Order Placed Successfully!
            </h2>
            <p className="text-sm text-emerald-700">
              Your personalised storybook for <strong>{childName}</strong> is on its way.
            </p>
            {/* Order reference */}
            <div className="mt-3 bg-white rounded-lg border border-emerald-200 px-4 py-2.5 inline-block">
              <p className="text-xs text-gray-500 mb-0.5">Order Reference</p>
              <p className="font-mono font-bold text-gray-800 tracking-wider text-sm">
                {order.order_id?.slice(0, 8).toUpperCase() || "—"}
              </p>
              <p className="text-xs text-gray-400 mt-0.5">Keep this for tracking</p>
            </div>
          </CardContent>
        </Card>

        {/* ── Status timeline ── */}
        <Card className="shadow-md mb-5">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Order Status</CardTitle>
              <Badge className={`border ${statusConf.color}`}>
                <StatusIcon className="w-3 h-3 mr-1" />
                {statusConf.label}
              </Badge>
            </div>
            <p className="text-xs text-gray-500 mt-1">{statusConf.description}</p>
          </CardHeader>
          <CardContent>
            {/* Visual timeline */}
            {status !== "cancelled" && (
              <div className="flex items-center justify-between mt-2 mb-1">
                {TIMELINE_STEPS.map((s, i) => {
                  const conf     = STATUS_CONFIG[s];
                  const Icon     = conf.icon;
                  const done     = conf.step <= statusConf.step;
                  const current  = s === status;
                  return (
                    <div key={s} className="flex flex-col items-center flex-1">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center
                        transition-colors text-xs
                        ${done
                          ? current
                            ? "bg-emerald-500 text-white ring-2 ring-emerald-200"
                            : "bg-emerald-400 text-white"
                          : "bg-gray-100 text-gray-400"
                        }`}>
                        {Icon && <Icon className="w-4 h-4" />}
                      </div>
                      <p className={`text-xs mt-1 text-center leading-tight
                        ${done ? "text-emerald-700 font-medium" : "text-gray-400"}`}>
                        {conf.label.split(" ")[0]}
                      </p>
                      {i < TIMELINE_STEPS.length - 1 && (
                        <div className={`hidden`} />
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* Timestamps */}
            <div className="space-y-1.5 mt-4 text-xs text-gray-500">
              {order.created_at   && <p>📋 Placed: {formatDate(order.created_at)}</p>}
              {order.confirmed_at && <p>✅ Confirmed: {formatDate(order.confirmed_at)}</p>}
              {order.shipped_at   && <p>🚚 Shipped: {formatDate(order.shipped_at)}</p>}
              {order.delivered_at && <p>🏠 Delivered: {formatDate(order.delivered_at)}</p>}
            </div>

            {/* Tracking info */}
            {order.tracking_id && (
              <div className="mt-3 bg-cyan-50 border border-cyan-200 rounded-lg px-3 py-2">
                <p className="text-xs text-cyan-700 font-medium">
                  🚚 Tracking: <span className="font-mono">{order.tracking_id}</span>
                  {order.courier && ` via ${order.courier}`}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Order details ── */}
        <Card className="shadow-md mb-5">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Order Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-emerald-500" />
                <div>
                  <p className="text-sm font-semibold text-gray-800">
                    {order.product_id?.includes("hardcover") ? "Hardcover" : "Paperback"} — A4
                  </p>
                  <p className="text-xs text-gray-500">
                    Personalised for {order.child_name || childName} · Qty: {order.quantity}
                  </p>
                </div>
              </div>
              <p className="text-lg font-black text-amber-600">
                {order.price_display || paise_to_display(order.total_amount_paise)}
              </p>
            </div>

            <Separator />

            {/* Beta notice */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2">
              <p className="text-xs text-blue-700">
                🎉 <strong>Beta period:</strong> This order is at no charge.
                We will print and ship your storybook free of cost.
              </p>
            </div>

            {/* Estimated delivery */}
            <div className="flex items-start gap-2 text-sm">
              <Truck className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
              <div>
                <p className="font-medium text-gray-700">Expected Delivery</p>
                <p className="text-gray-500 text-xs">
                  {order.product_id?.includes("hardcover")
                    ? "10–14 business days"
                    : "7–10 business days"}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* ── Delivery address ── */}
        {Object.keys(addr).length > 0 && (
          <Card className="shadow-md mb-5">
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <MapPin className="w-4 h-4 text-emerald-500" />
                Shipping To
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-gray-700 space-y-0.5">
                <p className="font-semibold">{addr.full_name}</p>
                <p>{addr.line1}{addr.line2 ? `, ${addr.line2}` : ""}</p>
                <p>{addr.city}, {addr.state} — {addr.pincode}</p>
                <p>{addr.country || "India"}</p>
                <p className="text-gray-500 text-xs mt-1">📞 {addr.phone}</p>
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Actions ── */}
        <div className="space-y-3">
          <Button
            onClick={() => navigate("/home")}
            className="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-5 font-semibold"
          >
            <RefreshCw className="mr-2 h-4 w-4" />Create Another Storybook
          </Button>
          <Button
            onClick={() => navigate("/home")}
            variant="outline"
            className="w-full py-5"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />Back to Home
          </Button>
        </div>

        <p className="text-center text-xs text-gray-400 mt-5">
          Order ID: <span className="font-mono">{order.order_id}</span>
        </p>
      </div>
    </div>
  );
}
