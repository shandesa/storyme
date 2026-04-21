/**
 * AdminOrdersPage.jsx
 * -------------------
 * Simple admin dashboard for managing print orders.
 *
 * Route: /admin/orders
 *
 * Authentication: X-Admin-Key header (set via env var ADMIN_SECRET_KEY).
 * The admin key is entered once per session and stored in component state
 * (not localStorage — security precaution).
 *
 * Features:
 *   - List all orders (all statuses, all users)
 *   - Filter by status
 *   - Update order status (pending → confirmed → printing → shipped → delivered)
 *   - Add tracking ID + courier when marking as shipped
 *   - View delivery address per order
 *   - Summary counts by status
 *
 * Design: deliberately simple — no complex UI framework needed for internal use.
 */

import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button }   from "@/components/ui/button";
import { Input }    from "@/components/ui/input";
import { Label }    from "@/components/ui/label";
import { Badge }    from "@/components/ui/badge";
import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import {
  Loader2, RefreshCw, ChevronDown, ChevronUp,
  Truck, Package, CheckCircle, Clock, Home, X, Lock,
} from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_V2      = `${BACKEND_URL}/api/v2`;

const STATUS_OPTIONS = [
  { value: "",           label: "All Orders" },
  { value: "pending",    label: "Pending" },
  { value: "confirmed",  label: "Confirmed" },
  { value: "printing",   label: "Printing" },
  { value: "shipped",    label: "Shipped" },
  { value: "delivered",  label: "Delivered" },
  { value: "cancelled",  label: "Cancelled" },
];

const STATUS_BADGE = {
  pending:   "bg-blue-100 text-blue-700",
  confirmed: "bg-purple-100 text-purple-700",
  printing:  "bg-amber-100 text-amber-700",
  shipped:   "bg-cyan-100 text-cyan-700",
  delivered: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-700",
};

const NEXT_STATUS = {
  pending:   "confirmed",
  confirmed: "printing",
  printing:  "shipped",
  shipped:   "delivered",
};

function paise(p) { return p ? `₹${p / 100}` : "—"; }
function fmtDate(s) {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleDateString("en-IN",
      {day:"numeric",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"});
  } catch { return s; }
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function AdminOrdersPage() {
  const [adminKey,    setAdminKey]    = useState("");
  const [authed,      setAuthed]      = useState(false);
  const [authError,   setAuthError]   = useState("");

  const [orders,      setOrders]      = useState([]);
  const [summary,     setSummary]     = useState({});
  const [loading,     setLoading]     = useState(false);
  const [statusFilter, setStatusFilter] = useState("");

  const [expandedId,  setExpandedId]  = useState(null);
  const [updateOrder, setUpdateOrder] = useState(null);  // order being updated
  const [updateForm,  setUpdateForm]  = useState({ status:"", tracking_id:"", courier:"", notes:"" });
  const [updating,    setUpdating]    = useState(false);

  // ── Auth ───────────────────────────────────────────────────────────────────

  const handleAuth = async (e) => {
    e.preventDefault();
    if (!adminKey.trim()) { setAuthError("Enter admin key"); return; }
    // Try a fetch to verify
    try {
      const res = await axios.get(`${API_V2}/admin/orders?limit=1`,
        { headers: { "X-Admin-Key": adminKey.trim() } });
      setAuthed(true);
      setAuthError("");
    } catch (err) {
      setAuthError(err.response?.data?.detail || "Invalid admin key");
    }
  };

  // ── Fetch orders ───────────────────────────────────────────────────────────

  const fetchOrders = useCallback(async () => {
    if (!authed) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: 200 });
      if (statusFilter) params.set("status", statusFilter);
      const res = await axios.get(`${API_V2}/admin/orders?${params}`,
        { headers: { "X-Admin-Key": adminKey } });
      setOrders(res.data.orders || []);
      setSummary(res.data.summary || {});
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to load orders");
    } finally {
      setLoading(false);
    }
  }, [authed, adminKey, statusFilter]);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  // ── Update order status ────────────────────────────────────────────────────

  const openUpdate = (order) => {
    setUpdateOrder(order);
    setUpdateForm({
      status:      NEXT_STATUS[order.status] || order.status,
      tracking_id: order.tracking_id || "",
      courier:     order.courier || "",
      notes:       order.notes || "",
    });
  };

  const handleUpdate = async () => {
    setUpdating(true);
    try {
      await axios.post(
        `${API_V2}/admin/orders/${updateOrder.order_id}/status`,
        updateForm,
        { headers: { "X-Admin-Key": adminKey } },
      );
      toast.success(`Order ${updateOrder.order_id.slice(0,8)} → ${updateForm.status}`);
      setUpdateOrder(null);
      fetchOrders();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Update failed");
    } finally {
      setUpdating(false);
    }
  };

  // ── Login screen ───────────────────────────────────────────────────────────

  if (!authed) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
        <Card className="w-full max-w-sm bg-gray-900 border-gray-800 shadow-2xl">
          <CardHeader className="text-center pb-2">
            <Lock className="w-8 h-8 text-amber-500 mx-auto mb-2" />
            <CardTitle className="text-white text-lg">StoryMe Admin</CardTitle>
            <p className="text-gray-400 text-sm">Order Management Dashboard</p>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleAuth} className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-gray-300 text-sm">Admin Key</Label>
                <Input
                  type="password"
                  placeholder="Enter ADMIN_SECRET_KEY"
                  value={adminKey}
                  onChange={(e) => setAdminKey(e.target.value)}
                  className="bg-gray-800 border-gray-700 text-white placeholder:text-gray-600"
                  autoFocus
                />
                {authError && (
                  <p className="text-red-400 text-xs">{authError}</p>
                )}
              </div>
              <Button type="submit" className="w-full bg-amber-500 hover:bg-amber-600 text-white">
                Sign In
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ── Dashboard ──────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gray-950 px-4 py-6 text-white">
      <div className="max-w-5xl mx-auto">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">Order Dashboard</h1>
            <p className="text-gray-400 text-sm">StoryMe Print Orders</p>
          </div>
          <Button
            onClick={fetchOrders}
            variant="outline"
            size="sm"
            disabled={loading}
            className="border-gray-700 text-gray-300 hover:bg-gray-800"
          >
            {loading
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : <RefreshCw className="w-4 h-4 mr-1" />
            }
            Refresh
          </Button>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-6">
          {Object.entries(summary).map(([s, n]) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s === statusFilter ? "" : s)}
              className={`rounded-lg border p-3 text-center transition-colors
                ${statusFilter === s
                  ? "border-amber-500 bg-amber-500/10"
                  : "border-gray-800 bg-gray-900 hover:border-gray-700"
                }`}
            >
              <p className="text-2xl font-black text-white">{n}</p>
              <p className="text-xs text-gray-400 capitalize">{s}</p>
            </button>
          ))}
        </div>

        {/* Status filter */}
        <div className="flex flex-wrap gap-2 mb-4">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setStatusFilter(opt.value)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors border
                ${statusFilter === opt.value
                  ? "bg-amber-500 border-amber-500 text-white"
                  : "border-gray-700 text-gray-400 hover:border-gray-500"
                }`}
            >
              {opt.label}
              {opt.value && summary[opt.value] != null && (
                <span className="ml-1 opacity-70">({summary[opt.value] || 0})</span>
              )}
            </button>
          ))}
        </div>

        {/* Orders table */}
        {loading && orders.length === 0 ? (
          <div className="text-center py-16 text-gray-500">
            <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3" />
            Loading orders…
          </div>
        ) : orders.length === 0 ? (
          <div className="text-center py-16 text-gray-500">
            No orders found{statusFilter ? ` with status "${statusFilter}"` : ""}.
          </div>
        ) : (
          <div className="space-y-3">
            {orders.map((order) => {
              const expanded  = expandedId === order.order_id;
              const canUpdate = NEXT_STATUS[order.status];
              const addr      = order.delivery_address || {};

              return (
                <Card key={order.order_id}
                  className="bg-gray-900 border-gray-800 overflow-hidden">
                  {/* Row */}
                  <div
                    className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-800/50"
                    onClick={() => setExpandedId(expanded ? null : order.order_id)}
                  >
                    {/* Status badge */}
                    <Badge className={`text-xs shrink-0 ${STATUS_BADGE[order.status] || ""}`}>
                      {order.status}
                    </Badge>

                    {/* Order info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-xs text-gray-400">
                          {order.order_id.slice(0,8).toUpperCase()}
                        </span>
                        <span className="text-white text-sm font-medium truncate">
                          {order.child_name || "—"}
                        </span>
                        <Badge variant="outline" className="border-gray-700 text-gray-400 text-xs">
                          {order.product_id?.includes("hardcover") ? "Hardcover" : "Paperback"}
                        </Badge>
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {fmtDate(order.created_at)} · {addr.city || "—"}, {addr.state || "—"}
                      </p>
                    </div>

                    {/* Price */}
                    <span className="text-amber-400 font-bold text-sm shrink-0">
                      {order.price_display || paise(order.total_amount_paise)}
                    </span>

                    {/* Expand */}
                    {expanded
                      ? <ChevronUp className="w-4 h-4 text-gray-500" />
                      : <ChevronDown className="w-4 h-4 text-gray-500" />
                    }
                  </div>

                  {/* Expanded detail */}
                  {expanded && (
                    <div className="border-t border-gray-800 px-4 py-4 space-y-4">
                      {/* Address */}
                      <div>
                        <p className="text-xs text-gray-500 uppercase mb-1">Delivery Address</p>
                        <div className="text-sm text-gray-300 space-y-0.5">
                          <p className="font-medium text-white">{addr.full_name}</p>
                          <p>{addr.line1}{addr.line2 ? `, ${addr.line2}` : ""}</p>
                          <p>{addr.city}, {addr.state} — {addr.pincode}</p>
                          <p className="text-gray-500">📞 {addr.phone}</p>
                        </div>
                      </div>

                      {/* Tracking */}
                      {order.tracking_id && (
                        <div>
                          <p className="text-xs text-gray-500 uppercase mb-1">Tracking</p>
                          <p className="text-sm text-cyan-400 font-mono">
                            {order.tracking_id}
                            {order.courier && <span className="text-gray-400 ml-2">via {order.courier}</span>}
                          </p>
                        </div>
                      )}

                      {/* Timestamps */}
                      <div className="text-xs text-gray-500 space-y-1">
                        {order.confirmed_at && <p>✅ Confirmed: {fmtDate(order.confirmed_at)}</p>}
                        {order.shipped_at   && <p>🚚 Shipped: {fmtDate(order.shipped_at)}</p>}
                        {order.delivered_at && <p>🏠 Delivered: {fmtDate(order.delivered_at)}</p>}
                        {order.cancelled_at && <p>❌ Cancelled: {fmtDate(order.cancelled_at)}</p>}
                        {order.notes        && <p>📝 Notes: {order.notes}</p>}
                      </div>

                      {/* Action buttons */}
                      <div className="flex gap-2 flex-wrap">
                        {canUpdate && (
                          <Button
                            size="sm"
                            onClick={() => openUpdate(order)}
                            className="bg-amber-500 hover:bg-amber-600 text-white text-xs"
                          >
                            Mark as {canUpdate.charAt(0).toUpperCase() + canUpdate.slice(1)}
                          </Button>
                        )}
                        {order.status !== "cancelled" && order.status !== "delivered" && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setUpdateOrder(order);
                              setUpdateForm({ status:"cancelled", tracking_id:"", courier:"", notes:"Cancelled by admin" });
                            }}
                            className="border-red-800 text-red-400 hover:bg-red-900/30 text-xs"
                          >
                            <X className="w-3 h-3 mr-1" />Cancel Order
                          </Button>
                        )}
                      </div>
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        )}

        {/* Update status dialog */}
        <Dialog open={!!updateOrder} onOpenChange={() => setUpdateOrder(null)}>
          <DialogContent className="bg-gray-900 border-gray-800 text-white">
            <DialogHeader>
              <DialogTitle>Update Order Status</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <p className="text-sm text-gray-400 mb-1">
                  Order: <span className="font-mono text-white">
                    {updateOrder?.order_id?.slice(0,8).toUpperCase()}
                  </span>
                </p>
                <p className="text-sm text-gray-400">
                  {updateOrder?.child_name} · {updateOrder?.product_id}
                </p>
              </div>

              <div className="space-y-1.5">
                <Label className="text-gray-300">New Status</Label>
                <select
                  value={updateForm.status}
                  onChange={(e) => setUpdateForm((f) => ({...f, status: e.target.value}))}
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white"
                >
                  {["pending","confirmed","printing","shipped","delivered","cancelled"].map((s) => (
                    <option key={s} value={s}>{s.charAt(0).toUpperCase()+s.slice(1)}</option>
                  ))}
                </select>
              </div>

              {updateForm.status === "shipped" && (
                <>
                  <div className="space-y-1.5">
                    <Label className="text-gray-300">Tracking ID</Label>
                    <Input
                      placeholder="e.g. BD123456789IN"
                      value={updateForm.tracking_id}
                      onChange={(e) => setUpdateForm((f) => ({...f, tracking_id: e.target.value}))}
                      className="bg-gray-800 border-gray-700 text-white"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-gray-300">Courier</Label>
                    <Input
                      placeholder="e.g. BlueDart, Delhivery"
                      value={updateForm.courier}
                      onChange={(e) => setUpdateForm((f) => ({...f, courier: e.target.value}))}
                      className="bg-gray-800 border-gray-700 text-white"
                    />
                  </div>
                </>
              )}

              <div className="space-y-1.5">
                <Label className="text-gray-300">Notes (optional)</Label>
                <Input
                  placeholder="Internal notes…"
                  value={updateForm.notes}
                  onChange={(e) => setUpdateForm((f) => ({...f, notes: e.target.value}))}
                  className="bg-gray-800 border-gray-700 text-white"
                />
              </div>
            </div>
            <DialogFooter className="gap-2">
              <Button variant="outline" onClick={() => setUpdateOrder(null)}
                className="border-gray-700 text-gray-300 hover:bg-gray-800">
                Cancel
              </Button>
              <Button onClick={handleUpdate} disabled={updating}
                className="bg-amber-500 hover:bg-amber-600 text-white">
                {updating ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
                Update Status
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

      </div>
    </div>
  );
}
