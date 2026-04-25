/**
 * UserAccountSheet.jsx
 * ---------------------
 * Slide-in side panel for "My Account" — accessible from every protected page
 * via AppHeader. Contains three sections:
 *
 *   1. Profile header — masked mobile number
 *   2. Tabs
 *      a. My Orders   — fetches GET /api/v2/orders
 *      b. My Addresses — fetches GET /api/v2/user/addresses + full CRUD
 *   3. Sign Out button
 *
 * Props:
 *   open         boolean   controlled open state
 *   onOpenChange function  called with new open state
 */

import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";

import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button }    from "@/components/ui/button";
import { Input }     from "@/components/ui/input";
import { Label }     from "@/components/ui/label";
import { Badge }     from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";

import {
  LogOut, Package, MapPin, Plus, Pencil, Trash2,
  Loader2, BookOpen, ChevronRight, Phone, Home,
  Briefcase, MoreHorizontal, X, Check,
} from "lucide-react";

import {
  getMobile, clearSession,
  stopInactivityTimer, stopTokenRefresh,
  authHeaders,
} from "@/lib/session";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_V2      = `${BACKEND_URL}/api/v2`;

// ─── Constants ────────────────────────────────────────────────────────────────

const INDIAN_STATES = [
  "Andhra Pradesh","Arunachal Pradesh","Assam","Bihar","Chhattisgarh",
  "Goa","Gujarat","Haryana","Himachal Pradesh","Jharkhand","Karnataka",
  "Kerala","Madhya Pradesh","Maharashtra","Manipur","Meghalaya","Mizoram",
  "Nagaland","Odisha","Punjab","Rajasthan","Sikkim","Tamil Nadu","Telangana",
  "Tripura","Uttar Pradesh","Uttarakhand","West Bengal",
  "Andaman and Nicobar Islands","Chandigarh","Dadra and Nagar Haveli",
  "Daman and Diu","Delhi","Jammu and Kashmir","Ladakh","Lakshadweep","Puducherry",
];

const ADDRESS_LABELS = ["Home", "Office", "Other"];

const ORDER_STATUS = {
  // Print (offline) statuses
  pending:   { label: "Received",  color: "bg-blue-100 text-blue-700 border-blue-200" },
  confirmed: { label: "Confirmed", color: "bg-purple-100 text-purple-700 border-purple-200" },
  printing:  { label: "Printing",  color: "bg-amber-100 text-amber-700 border-amber-200" },
  shipped:   { label: "Shipped",   color: "bg-cyan-100 text-cyan-700 border-cyan-200" },
  delivered: { label: "Delivered", color: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  cancelled: { label: "Cancelled", color: "bg-red-100 text-red-700 border-red-200" },
  // Digital (online) statuses
  order_received:  { label: "Received",   color: "bg-blue-100 text-blue-700 border-blue-200" },
  payment_pending: { label: "Payment",    color: "bg-amber-100 text-amber-700 border-amber-200" },
  generating:      { label: "Generating", color: "bg-purple-100 text-purple-700 border-purple-200" },
  emailed:         { label: "Delivered",  color: "bg-emerald-100 text-emerald-700 border-emerald-200" },
};

const EMPTY_ADDRESS = {
  label: "Home", full_name: "", line1: "", line2: "",
  city: "", state: "", pincode: "", phone: "",
};

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-IN", {
      day: "numeric", month: "short", year: "numeric",
    });
  } catch { return iso; }
}

// ─── Address label icon ────────────────────────────────────────────────────────

function LabelIcon({ label }) {
  if (label === "Home")   return <Home className="w-3.5 h-3.5" />;
  if (label === "Office") return <Briefcase className="w-3.5 h-3.5" />;
  return <MoreHorizontal className="w-3.5 h-3.5" />;
}

// ─── AddressForm (inline — used for add and edit) ─────────────────────────────

function AddressForm({ initial, onSave, onCancel, saving }) {
  const [form, setForm]   = useState({ ...EMPTY_ADDRESS, ...initial });
  const [errors, setErrors] = useState({});

  const set = (field, value) => {
    setForm(p => ({ ...p, [field]: value }));
    if (errors[field]) setErrors(p => ({ ...p, [field]: undefined }));
  };

  const validate = () => {
    const e = {};
    if (!form.full_name?.trim())          e.full_name = "Required";
    if (!form.line1?.trim())              e.line1     = "Required";
    if (!form.city?.trim())               e.city      = "Required";
    if (!form.state?.trim())              e.state     = "Required";
    if (!/^\d{6}$/.test(form.pincode))    e.pincode   = "6-digit pincode";
    if (!/^\d{10}$/.test(form.phone))     e.phone     = "10-digit number";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = () => {
    if (validate()) onSave(form);
  };

  return (
    <div className="space-y-3 pt-1">
      {/* Label chips */}
      <div className="space-y-1">
        <Label className="text-xs text-gray-500">Label</Label>
        <div className="flex gap-2">
          {ADDRESS_LABELS.map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => set("label", l)}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors
                ${form.label === l
                  ? "bg-emerald-600 border-emerald-600 text-white"
                  : "bg-white border-gray-300 text-gray-600 hover:border-emerald-400"}`}
            >
              {l}
            </button>
          ))}
          {!ADDRESS_LABELS.includes(form.label) && (
            <span className="px-3 py-1 rounded-full text-xs font-medium border bg-emerald-600 border-emerald-600 text-white">
              {form.label}
            </span>
          )}
        </div>
      </div>

      {/* Full name */}
      <div className="space-y-1">
        <Label className="text-xs text-gray-600 font-medium">Full Name *</Label>
        <Input
          placeholder="Recipient's full name"
          value={form.full_name}
          onChange={(e) => set("full_name", e.target.value)}
          className={`h-9 text-sm ${errors.full_name ? "border-red-400" : "border-gray-300"}`}
        />
        {errors.full_name && <p className="text-red-500 text-xs">{errors.full_name}</p>}
      </div>

      {/* Phone */}
      <div className="space-y-1">
        <Label className="text-xs text-gray-600 font-medium">Phone *</Label>
        <Input
          placeholder="10-digit mobile"
          value={form.phone}
          maxLength={10}
          onChange={(e) => set("phone", e.target.value.replace(/\D/g, ""))}
          className={`h-9 text-sm ${errors.phone ? "border-red-400" : "border-gray-300"}`}
        />
        {errors.phone && <p className="text-red-500 text-xs">{errors.phone}</p>}
      </div>

      {/* Line 1 */}
      <div className="space-y-1">
        <Label className="text-xs text-gray-600 font-medium">Address Line 1 *</Label>
        <Input
          placeholder="House/flat no., building, street"
          value={form.line1}
          onChange={(e) => set("line1", e.target.value)}
          className={`h-9 text-sm ${errors.line1 ? "border-red-400" : "border-gray-300"}`}
        />
        {errors.line1 && <p className="text-red-500 text-xs">{errors.line1}</p>}
      </div>

      {/* Line 2 */}
      <div className="space-y-1">
        <Label className="text-xs text-gray-600 font-medium">Address Line 2</Label>
        <Input
          placeholder="Area, landmark (optional)"
          value={form.line2}
          onChange={(e) => set("line2", e.target.value)}
          className="h-9 text-sm border-gray-300"
        />
      </div>

      {/* City + Pincode row */}
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs text-gray-600 font-medium">City *</Label>
          <Input
            placeholder="City"
            value={form.city}
            onChange={(e) => set("city", e.target.value)}
            className={`h-9 text-sm ${errors.city ? "border-red-400" : "border-gray-300"}`}
          />
          {errors.city && <p className="text-red-500 text-xs">{errors.city}</p>}
        </div>
        <div className="space-y-1">
          <Label className="text-xs text-gray-600 font-medium">Pincode *</Label>
          <Input
            placeholder="6 digits"
            value={form.pincode}
            maxLength={6}
            onChange={(e) => set("pincode", e.target.value.replace(/\D/g, ""))}
            className={`h-9 text-sm ${errors.pincode ? "border-red-400" : "border-gray-300"}`}
          />
          {errors.pincode && <p className="text-red-500 text-xs">{errors.pincode}</p>}
        </div>
      </div>

      {/* State */}
      <div className="space-y-1">
        <Label className="text-xs text-gray-600 font-medium">State *</Label>
        <select
          value={form.state}
          onChange={(e) => set("state", e.target.value)}
          className={`w-full rounded-md border px-3 py-2 text-sm bg-white text-gray-900
            focus:outline-none focus:ring-2 focus:ring-emerald-400
            ${errors.state ? "border-red-400" : "border-gray-300"}`}
        >
          <option value="">Select state</option>
          {INDIAN_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {errors.state && <p className="text-red-500 text-xs">{errors.state}</p>}
      </div>

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        <Button
          onClick={handleSubmit}
          disabled={saving}
          size="sm"
          className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />}
          Save Address
        </Button>
        <Button onClick={onCancel} variant="outline" size="sm">
          <X className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
}

// ─── My Orders Tab ────────────────────────────────────────────────────────────

function MyOrdersTab({ onClose }) {
  const navigate = useNavigate();
  const [orders,  setOrders]  = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios
      .get(`${API_V2}/orders`, { headers: authHeaders() })
      .then((res) => setOrders(res.data.orders || []))
      .catch(() => toast.error("Could not load orders."))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="py-10 flex flex-col items-center gap-3 text-gray-400">
        <Loader2 className="w-7 h-7 animate-spin" />
        <p className="text-sm">Loading orders…</p>
      </div>
    );
  }

  if (orders.length === 0) {
    return (
      <div className="py-10 text-center space-y-3">
        <div className="w-14 h-14 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
          <Package className="w-7 h-7 text-gray-400" />
        </div>
        <p className="text-sm font-medium text-gray-600">No orders yet</p>
        <p className="text-xs text-gray-400">Your printed storybook orders will appear here.</p>
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
      {orders.map((order) => {
        const sc       = ORDER_STATUS[order.status] || ORDER_STATUS.pending;
        const ref      = (order.order_id || "").slice(0, 8).toUpperCase();
        const otype    = order.order_type || "print";
        const isDigital = otype === "pdf_download" || otype === "email_pdf";
        const typeLabel = otype === "pdf_download" ? "PDF Download"
          : otype === "email_pdf" ? "Email PDF"
          : ((order.product_id || "").includes("hardcover") ? "Hardcover" : "Paperback");
        const price = order.price_display || (isDigital ? "₹199" : "");

        return (
          <button
            key={order.order_id}
            onClick={() => {
              onClose();
              navigate(`/order-status/${order.order_id}`, {
                state: { order, orderType: otype },
              });
            }}
            className="w-full text-left rounded-xl border border-gray-200 bg-white
              hover:border-emerald-300 hover:shadow-sm
              transition-all duration-150 px-4 py-3 group"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-mono text-xs font-bold text-gray-700">#{ref}</span>
                  <Badge className={`text-xs border px-2 py-0 ${sc.color}`}>
                    {sc.label}
                  </Badge>
                  <Badge className={`text-xs border px-2 py-0 ${
                    isDigital
                      ? "bg-indigo-50 text-indigo-600 border-indigo-200"
                      : "bg-amber-50 text-amber-700 border-amber-200"
                  }`}>
                    {isDigital ? "🌐 Online" : "📦 Print"}
                  </Badge>
                </div>
                <p className="text-sm font-medium text-gray-800 truncate">
                  {typeLabel} — {price}
                </p>
                {order.child_name && (
                  <p className="text-xs text-gray-500 mt-0.5">
                    <BookOpen className="inline w-3 h-3 mr-0.5" />
                    For {order.child_name}
                  </p>
                )}
                <p className="text-xs text-gray-400 mt-0.5">{fmtDate(order.created_at)}</p>
              </div>
              <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-emerald-500
                mt-1 flex-shrink-0 transition-colors" />
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ─── My Addresses Tab ─────────────────────────────────────────────────────────

function MyAddressesTab({ onAddressesChange }) {
  const [addresses,  setAddresses]  = useState([]);
  const [loading,    setLoading]    = useState(true);
  const [canAdd,     setCanAdd]     = useState(true);
  const [showForm,   setShowForm]   = useState(false);   // add form visible
  const [editId,     setEditId]     = useState(null);    // address_id being edited
  const [deleteId,   setDeleteId]   = useState(null);    // address_id pending delete confirm
  const [saving,     setSaving]     = useState(false);
  const [deleting,   setDeleting]   = useState(false);

  const fetchAddresses = useCallback(() => {
    setLoading(true);
    axios
      .get(`${API_V2}/user/addresses`, { headers: authHeaders() })
      .then((res) => {
        setAddresses(res.data.addresses || []);
        setCanAdd(res.data.can_add !== false);
        if (onAddressesChange) onAddressesChange(res.data.addresses || []);
      })
      .catch(() => toast.error("Could not load addresses."))
      .finally(() => setLoading(false));
  }, [onAddressesChange]);

  useEffect(() => { fetchAddresses(); }, [fetchAddresses]);

  const handleSaveNew = async (form) => {
    setSaving(true);
    try {
      await axios.post(`${API_V2}/user/addresses`, form, { headers: authHeaders() });
      toast.success("Address saved!");
      setShowForm(false);
      fetchAddresses();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to save address.");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveEdit = async (form) => {
    setSaving(true);
    try {
      await axios.put(`${API_V2}/user/addresses/${editId}`, form, { headers: authHeaders() });
      toast.success("Address updated!");
      setEditId(null);
      fetchAddresses();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to update address.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await axios.delete(`${API_V2}/user/addresses/${deleteId}`, { headers: authHeaders() });
      toast.success("Address removed.");
      setDeleteId(null);
      fetchAddresses();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to delete address.");
    } finally {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="py-10 flex flex-col items-center gap-3 text-gray-400">
        <Loader2 className="w-7 h-7 animate-spin" />
        <p className="text-sm">Loading addresses…</p>
      </div>
    );
  }

  const editingAddress = addresses.find((a) => a.address_id === editId);

  return (
    <div className="space-y-3">
      {/* Address cards */}
      {addresses.map((addr) => (
        <div key={addr.address_id} className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          {editId === addr.address_id ? (
            /* ── Inline edit form ── */
            <div className="p-4">
              <p className="text-sm font-semibold text-gray-700 mb-3">Edit Address</p>
              <AddressForm
                initial={editingAddress}
                onSave={handleSaveEdit}
                onCancel={() => setEditId(null)}
                saving={saving}
              />
            </div>
          ) : (
            /* ── Address display ── */
            <div className="px-4 py-3">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-1.5 mb-1">
                  <LabelIcon label={addr.label} />
                  <span className="text-xs font-semibold text-gray-700">{addr.label}</span>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => { setEditId(addr.address_id); setShowForm(false); }}
                    className="p-1.5 rounded-lg text-gray-400 hover:text-emerald-600
                      hover:bg-emerald-50 transition-colors"
                    aria-label="Edit address"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setDeleteId(addr.address_id)}
                    className="p-1.5 rounded-lg text-gray-400 hover:text-red-500
                      hover:bg-red-50 transition-colors"
                    aria-label="Delete address"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              <p className="text-sm font-medium text-gray-800">{addr.full_name}</p>
              <p className="text-xs text-gray-500 leading-relaxed mt-0.5">
                {addr.line1}{addr.line2 ? `, ${addr.line2}` : ""}
              </p>
              <p className="text-xs text-gray-500">
                {addr.city}, {addr.state} — {addr.pincode}
              </p>
              <div className="flex items-center gap-1 mt-1">
                <Phone className="w-3 h-3 text-gray-400" />
                <span className="text-xs text-gray-400">{addr.phone}</span>
              </div>
            </div>
          )}
        </div>
      ))}

      {/* Empty state */}
      {addresses.length === 0 && !showForm && (
        <div className="py-8 text-center space-y-2">
          <div className="w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
            <MapPin className="w-6 h-6 text-gray-400" />
          </div>
          <p className="text-sm font-medium text-gray-600">No saved addresses</p>
          <p className="text-xs text-gray-400">Save addresses for faster checkout.</p>
        </div>
      )}

      {/* Add form */}
      {showForm && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-sm font-semibold text-gray-700 mb-3">New Address</p>
          <AddressForm
            initial={EMPTY_ADDRESS}
            onSave={handleSaveNew}
            onCancel={() => setShowForm(false)}
            saving={saving}
          />
        </div>
      )}

      {/* Add button */}
      {!showForm && !editId && canAdd && (
        <button
          onClick={() => { setShowForm(true); setEditId(null); }}
          className="w-full rounded-xl border-2 border-dashed border-gray-300
            hover:border-emerald-400 hover:bg-emerald-50
            py-3 flex items-center justify-center gap-2
            text-sm font-medium text-gray-500 hover:text-emerald-600
            transition-all duration-150"
        >
          <Plus className="w-4 h-4" />
          Add New Address
        </button>
      )}

      {!canAdd && (
        <p className="text-xs text-center text-gray-400">
          Maximum 10 addresses reached. Delete one to add another.
        </p>
      )}

      {/* Delete confirmation */}
      <AlertDialog open={!!deleteId} onOpenChange={(o) => { if (!o) setDeleteId(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this address?</AlertDialogTitle>
            <AlertDialogDescription>
              This address will be permanently removed from your address book.
              This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleting}
              className="bg-red-500 hover:bg-red-600 text-white"
            >
              {deleting ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : null}
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ─── Main Sheet ───────────────────────────────────────────────────────────────

export default function UserAccountSheet({ open, onOpenChange }) {
  const navigate = useNavigate();
  const mobile   = getMobile() || "";

  const handleSignOut = () => {
    onOpenChange(false);
    clearSession();
    stopInactivityTimer();
    stopTokenRefresh();
    navigate("/", { replace: true });
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-md flex flex-col p-0 overflow-hidden"
        aria-label="My Account"
      >
        {/* ── Header ── */}
        <SheetHeader className="px-5 pt-5 pb-4 border-b border-gray-100">
          <SheetTitle className="text-left text-gray-900">My Account</SheetTitle>
          {mobile && (
            <div className="flex items-center gap-2 mt-1">
              <div className="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center">
                <span className="text-xs font-bold text-emerald-700">
                  {mobile.slice(-2)}
                </span>
              </div>
              <span className="text-sm text-gray-600">+91 {mobile}</span>
            </div>
          )}
        </SheetHeader>

        {/* ── Tabs ── */}
        <div className="flex-1 overflow-y-auto">
          <Tabs defaultValue="orders" className="h-full flex flex-col">
            <TabsList className="mx-5 mt-4 mb-0 grid grid-cols-2 h-9">
              <TabsTrigger value="orders" className="text-xs">
                <Package className="w-3.5 h-3.5 mr-1.5" />My Orders
              </TabsTrigger>
              <TabsTrigger value="addresses" className="text-xs">
                <MapPin className="w-3.5 h-3.5 mr-1.5" />Saved Addresses
              </TabsTrigger>
            </TabsList>

            <TabsContent value="orders" className="flex-1 px-5 pt-4 pb-4 mt-0">
              <MyOrdersTab onClose={() => onOpenChange(false)} />
            </TabsContent>

            <TabsContent value="addresses" className="flex-1 px-5 pt-4 pb-4 mt-0">
              <MyAddressesTab />
            </TabsContent>
          </Tabs>
        </div>

        {/* ── Footer ── */}
        <div className="px-5 py-4 border-t border-gray-100 bg-white">
          <Button
            variant="outline"
            onClick={handleSignOut}
            className="w-full border-red-200 text-red-500 hover:bg-red-50 hover:text-red-600
              hover:border-red-300 transition-colors"
          >
            <LogOut className="w-4 h-4 mr-2" />
            Sign Out
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ─── Exported hook for PrintOrderPage address pre-fill ────────────────────────

/**
 * useSavedAddresses()
 * Fetches the user's saved addresses. Used by PrintOrderPage to show
 * a "Use saved address" selector above the manual form.
 *
 * Returns: { addresses, loading, refetch }
 */
export function useSavedAddresses() {
  const [addresses, setAddresses] = useState([]);
  const [loading,   setLoading]   = useState(true);

  const fetch = useCallback(() => {
    setLoading(true);
    axios
      .get(`${API_V2}/user/addresses`, { headers: authHeaders() })
      .then((res) => setAddresses(res.data.addresses || []))
      .catch(() => setAddresses([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  return { addresses, loading, refetch: fetch };
}
