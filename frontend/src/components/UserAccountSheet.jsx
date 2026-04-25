/**
 * UserAccountSheet.jsx
 * ---------------------
 * Slide-in side panel for "My Account" — accessible from every protected page
 * via AppHeader.
 *
 * Tabs:
 *   1. My Orders      — fetches GET /api/v2/orders
 *   2. Saved Addresses — fetches GET /api/v2/user/addresses + full CRUD
 *   3. Profile        — display name, email, change password, delete account
 *
 * Props:
 *   open         boolean   controlled open state
 *   onOpenChange function  called with new open state
 *
 * See docs/my-account/MY_ACCOUNT_DESIGN.md for full feature design.
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
  Briefcase, MoreHorizontal, X, Check, User,
  Mail, Lock, Eye, EyeOff, Shield, AlertTriangle,
  Calendar, Settings,
} from "lucide-react";

import {
  getMobile, clearSession,
  stopInactivityTimer, stopTokenRefresh,
  authHeaders,
} from "@/lib/session";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_V2      = `${BACKEND_URL}/api/v2`;
const API_AUTH    = `${BACKEND_URL}/api/auth`;

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
  // Print (offline)
  pending:   { label: "Received",  color: "bg-blue-100 text-blue-700 border-blue-200" },
  confirmed: { label: "Confirmed", color: "bg-purple-100 text-purple-700 border-purple-200" },
  printing:  { label: "Printing",  color: "bg-amber-100 text-amber-700 border-amber-200" },
  shipped:   { label: "Shipped",   color: "bg-cyan-100 text-cyan-700 border-cyan-200" },
  delivered: { label: "Delivered", color: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  cancelled: { label: "Cancelled", color: "bg-red-100 text-red-700 border-red-200" },
  // Digital (online)
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

// ─── Shared UI helpers ────────────────────────────────────────────────────────

function LabelIcon({ label }) {
  if (label === "Home")   return <Home className="w-3.5 h-3.5" />;
  if (label === "Office") return <Briefcase className="w-3.5 h-3.5" />;
  return <MoreHorizontal className="w-3.5 h-3.5" />;
}

// ─── AddressForm ──────────────────────────────────────────────────────────────

function AddressForm({ initial, onSave, onCancel, saving }) {
  const [form, setForm]     = useState({ ...EMPTY_ADDRESS, ...initial });
  const [errors, setErrors] = useState({});

  const set = (field, value) => {
    setForm(p => ({ ...p, [field]: value }));
    if (errors[field]) setErrors(p => ({ ...p, [field]: undefined }));
  };

  const validate = () => {
    const e = {};
    if (!form.full_name?.trim())        e.full_name = "Required";
    if (!form.line1?.trim())            e.line1     = "Required";
    if (!form.city?.trim())             e.city      = "Required";
    if (!form.state?.trim())            e.state     = "Required";
    if (!/^\d{6}$/.test(form.pincode))  e.pincode   = "6-digit pincode";
    if (!/^\d{10}$/.test(form.phone))   e.phone     = "10-digit number";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  return (
    <div className="space-y-3 pt-1">
      <div className="space-y-1">
        <Label className="text-xs text-gray-500">Label</Label>
        <div className="flex gap-2">
          {ADDRESS_LABELS.map((l) => (
            <button key={l} type="button" onClick={() => set("label", l)}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors
                ${form.label === l
                  ? "bg-emerald-600 border-emerald-600 text-white"
                  : "bg-white border-gray-300 text-gray-600 hover:border-emerald-400"}`}>
              {l}
            </button>
          ))}
        </div>
      </div>
      {[
        { f: "full_name", label: "Full Name *", ph: "Recipient's full name" },
        { f: "phone",     label: "Phone *",     ph: "10-digit mobile", max: 10,
          onChange: (e) => set("phone", e.target.value.replace(/\D/g, "")) },
        { f: "line1",     label: "Address Line 1 *", ph: "House/flat no., building, street" },
        { f: "line2",     label: "Address Line 2", ph: "Area, landmark (optional)" },
      ].map(({ f, label, ph, max, onChange }) => (
        <div className="space-y-1" key={f}>
          <Label className="text-xs text-gray-600 font-medium">{label}</Label>
          <Input placeholder={ph} value={form[f]}
            onChange={onChange || ((e) => set(f, e.target.value))}
            maxLength={max}
            className={`h-9 text-sm ${errors[f] ? "border-red-400" : "border-gray-300"}`} />
          {errors[f] && <p className="text-red-500 text-xs">{errors[f]}</p>}
        </div>
      ))}
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs text-gray-600 font-medium">City *</Label>
          <Input placeholder="City" value={form.city}
            onChange={(e) => set("city", e.target.value)}
            className={`h-9 text-sm ${errors.city ? "border-red-400" : "border-gray-300"}`} />
          {errors.city && <p className="text-red-500 text-xs">{errors.city}</p>}
        </div>
        <div className="space-y-1">
          <Label className="text-xs text-gray-600 font-medium">Pincode *</Label>
          <Input placeholder="6 digits" value={form.pincode} maxLength={6}
            onChange={(e) => set("pincode", e.target.value.replace(/\D/g, ""))}
            className={`h-9 text-sm ${errors.pincode ? "border-red-400" : "border-gray-300"}`} />
          {errors.pincode && <p className="text-red-500 text-xs">{errors.pincode}</p>}
        </div>
      </div>
      <div className="space-y-1">
        <Label className="text-xs text-gray-600 font-medium">State *</Label>
        <select value={form.state} onChange={(e) => set("state", e.target.value)}
          className={`w-full rounded-md border px-3 py-2 text-sm bg-white text-gray-900
            focus:outline-none focus:ring-2 focus:ring-emerald-400
            ${errors.state ? "border-red-400" : "border-gray-300"}`}>
          <option value="">Select state</option>
          {INDIAN_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {errors.state && <p className="text-red-500 text-xs">{errors.state}</p>}
      </div>
      <div className="flex gap-2 pt-1">
        <Button onClick={() => { if (validate()) onSave(form); }}
          disabled={saving} size="sm"
          className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white">
          {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />}
          Save Address
        </Button>
        <Button onClick={onCancel} variant="outline" size="sm"><X className="w-4 h-4" /></Button>
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
    axios.get(`${API_V2}/orders`, { headers: authHeaders() })
      .then((res) => setOrders(res.data.orders || []))
      .catch(() => toast.error("Could not load orders."))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="py-10 flex flex-col items-center gap-3 text-gray-400">
      <Loader2 className="w-7 h-7 animate-spin" /><p className="text-sm">Loading orders…</p>
    </div>
  );

  if (orders.length === 0) return (
    <div className="py-10 text-center space-y-3">
      <div className="w-14 h-14 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
        <Package className="w-7 h-7 text-gray-400" />
      </div>
      <p className="text-sm font-medium text-gray-600">No orders yet</p>
      <p className="text-xs text-gray-400">Your storybook orders will appear here.</p>
    </div>
  );

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
          <button key={order.order_id}
            onClick={() => { onClose(); navigate(`/order-status/${order.order_id}`, { state: { order, orderType: otype } }); }}
            className="w-full text-left rounded-xl border border-gray-200 bg-white
              hover:border-emerald-300 hover:shadow-sm transition-all duration-150 px-4 py-3 group">
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className="font-mono text-xs font-bold text-gray-700">#{ref}</span>
                  <Badge className={`text-xs border px-2 py-0 ${sc.color}`}>{sc.label}</Badge>
                  <Badge className={`text-xs border px-2 py-0 ${isDigital ? "bg-indigo-50 text-indigo-600 border-indigo-200" : "bg-amber-50 text-amber-700 border-amber-200"}`}>
                    {isDigital ? "🌐 Online" : "📦 Print"}
                  </Badge>
                </div>
                <p className="text-sm font-medium text-gray-800 truncate">{typeLabel} — {price}</p>
                {order.child_name && (
                  <p className="text-xs text-gray-500 mt-0.5">
                    <BookOpen className="inline w-3 h-3 mr-0.5" />For {order.child_name}
                  </p>
                )}
                <p className="text-xs text-gray-400 mt-0.5">{fmtDate(order.created_at)}</p>
              </div>
              <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-emerald-500 mt-1 flex-shrink-0 transition-colors" />
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ─── My Addresses Tab ─────────────────────────────────────────────────────────

function MyAddressesTab({ onAddressesChange }) {
  const [addresses, setAddresses] = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [canAdd,    setCanAdd]    = useState(true);
  const [showForm,  setShowForm]  = useState(false);
  const [editId,    setEditId]    = useState(null);
  const [deleteId,  setDeleteId]  = useState(null);
  const [saving,    setSaving]    = useState(false);
  const [deleting,  setDeleting]  = useState(false);

  const fetchAddresses = useCallback(() => {
    setLoading(true);
    axios.get(`${API_V2}/user/addresses`, { headers: authHeaders() })
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
      toast.success("Address saved!"); setShowForm(false); fetchAddresses();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to save address.");
    } finally { setSaving(false); }
  };

  const handleSaveEdit = async (form) => {
    setSaving(true);
    try {
      await axios.put(`${API_V2}/user/addresses/${editId}`, form, { headers: authHeaders() });
      toast.success("Address updated!"); setEditId(null); fetchAddresses();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to update address.");
    } finally { setSaving(false); }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await axios.delete(`${API_V2}/user/addresses/${deleteId}`, { headers: authHeaders() });
      toast.success("Address removed."); setDeleteId(null); fetchAddresses();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to delete address.");
    } finally { setDeleting(false); }
  };

  if (loading) return (
    <div className="py-10 flex flex-col items-center gap-3 text-gray-400">
      <Loader2 className="w-7 h-7 animate-spin" /><p className="text-sm">Loading addresses…</p>
    </div>
  );

  return (
    <div className="space-y-3">
      {addresses.map((addr) => (
        <div key={addr.address_id} className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          {editId === addr.address_id ? (
            <div className="p-4">
              <p className="text-sm font-semibold text-gray-700 mb-3">Edit Address</p>
              <AddressForm initial={addresses.find(a => a.address_id === editId)}
                onSave={handleSaveEdit} onCancel={() => setEditId(null)} saving={saving} />
            </div>
          ) : (
            <div className="px-4 py-3">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-1.5 mb-1">
                  <LabelIcon label={addr.label} />
                  <span className="text-xs font-semibold text-gray-700">{addr.label}</span>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => { setEditId(addr.address_id); setShowForm(false); }}
                    className="p-1.5 rounded-lg text-gray-400 hover:text-emerald-600 hover:bg-emerald-50 transition-colors">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => setDeleteId(addr.address_id)}
                    className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              <p className="text-sm font-medium text-gray-800">{addr.full_name}</p>
              <p className="text-xs text-gray-500 leading-relaxed mt-0.5">
                {addr.line1}{addr.line2 ? `, ${addr.line2}` : ""}
              </p>
              <p className="text-xs text-gray-500">{addr.city}, {addr.state} — {addr.pincode}</p>
              <div className="flex items-center gap-1 mt-1">
                <Phone className="w-3 h-3 text-gray-400" />
                <span className="text-xs text-gray-400">{addr.phone}</span>
              </div>
            </div>
          )}
        </div>
      ))}

      {addresses.length === 0 && !showForm && (
        <div className="py-8 text-center space-y-2">
          <div className="w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
            <MapPin className="w-6 h-6 text-gray-400" />
          </div>
          <p className="text-sm font-medium text-gray-600">No saved addresses</p>
          <p className="text-xs text-gray-400">Save addresses for faster checkout.</p>
        </div>
      )}

      {showForm && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-sm font-semibold text-gray-700 mb-3">New Address</p>
          <AddressForm initial={EMPTY_ADDRESS} onSave={handleSaveNew}
            onCancel={() => setShowForm(false)} saving={saving} />
        </div>
      )}

      {!showForm && !editId && canAdd && (
        <button onClick={() => { setShowForm(true); setEditId(null); }}
          className="w-full rounded-xl border-2 border-dashed border-gray-300
            hover:border-emerald-400 hover:bg-emerald-50 py-3
            flex items-center justify-center gap-2
            text-sm font-medium text-gray-500 hover:text-emerald-600 transition-all">
          <Plus className="w-4 h-4" />Add New Address
        </button>
      )}
      {!canAdd && (
        <p className="text-xs text-center text-gray-400">
          Maximum 10 addresses reached. Delete one to add another.
        </p>
      )}

      <AlertDialog open={!!deleteId} onOpenChange={(o) => { if (!o) setDeleteId(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this address?</AlertDialogTitle>
            <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} disabled={deleting}
              className="bg-red-500 hover:bg-red-600 text-white">
              {deleting && <Loader2 className="w-4 h-4 animate-spin mr-1" />}Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ─── Profile Tab ──────────────────────────────────────────────────────────────

function ProfileTab({ mobile, onProfileUpdate, onSignOut }) {
  const [profile, setProfile]   = useState(null);
  const [loading, setLoading]   = useState(true);

  // Personal info state
  const [displayName, setDisplayName] = useState("");
  const [email,       setEmail]       = useState("");
  const [savingInfo,  setSavingInfo]  = useState(false);

  // Password state
  const [currentPw, setCurrentPw]   = useState("");
  const [newPw,     setNewPw]       = useState("");
  const [confirmPw, setConfirmPw]   = useState("");
  const [showCur,   setShowCur]     = useState(false);
  const [showNew,   setShowNew]     = useState(false);
  const [showCon,   setShowCon]     = useState(false);
  const [savingPw,  setSavingPw]    = useState(false);

  // Delete account state
  const [deleteDialog, setDeleteDialog]   = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deletePw,      setDeletePw]      = useState("");
  const [deleting,      setDeleting]      = useState(false);

  // Fetch profile on mount
  useEffect(() => {
    axios.get(`${API_V2}/user/profile`, { headers: authHeaders() })
      .then((res) => {
        setProfile(res.data);
        setDisplayName(res.data.display_name || "");
        setEmail(res.data.email || "");
      })
      .catch(() => toast.error("Could not load profile."))
      .finally(() => setLoading(false));
  }, []);

  // ── Save personal info ────────────────────────────────────────────────────
  const handleSaveInfo = async () => {
    // Basic email validation
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      toast.error("Please enter a valid email address."); return;
    }
    setSavingInfo(true);
    try {
      const res = await axios.put(
        `${API_V2}/user/profile`,
        { display_name: displayName.trim(), email: email.trim() },
        { headers: authHeaders() },
      );
      toast.success("Profile updated!");
      if (onProfileUpdate) onProfileUpdate(res.data.display_name, res.data.email);
      setProfile(p => ({ ...p, display_name: res.data.display_name, email: res.data.email }));
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to update profile.");
    } finally { setSavingInfo(false); }
  };

  // ── Change password ────────────────────────────────────────────────────────
  const handleChangePassword = async () => {
    if (!currentPw) { toast.error("Please enter your current password."); return; }
    if (newPw.length < 6) { toast.error("New password must be at least 6 characters."); return; }
    if (newPw !== confirmPw) { toast.error("New passwords do not match."); return; }
    if (newPw === currentPw) { toast.error("New password must be different from the current one."); return; }

    setSavingPw(true);
    try {
      await axios.post(
        `${API_V2}/user/password`,
        { current_password: currentPw, new_password: newPw },
        { headers: authHeaders() },
      );
      toast.success("Password changed successfully!");
      setCurrentPw(""); setNewPw(""); setConfirmPw("");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to change password.");
    } finally { setSavingPw(false); }
  };

  // ── Delete account ─────────────────────────────────────────────────────────
  const handleDeleteAccount = async () => {
    if (deleteConfirm !== "DELETE") {
      toast.error('Please type DELETE (uppercase) to confirm.'); return;
    }
    setDeleting(true);
    try {
      await axios.delete(
        `${API_V2}/user/account`,
        {
          headers: authHeaders(),
          data: { confirmation: "DELETE", current_password: deletePw || undefined },
        },
      );
      toast.success("Account deletion requested. You will be signed out.");
      setTimeout(() => { setDeleteDialog(false); onSignOut(); }, 1500);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to request deletion.");
    } finally { setDeleting(false); }
  };

  if (loading) return (
    <div className="py-10 flex flex-col items-center gap-3 text-gray-400">
      <Loader2 className="w-7 h-7 animate-spin" /><p className="text-sm">Loading profile…</p>
    </div>
  );

  const hasPassword = !!profile?.password_hash_set; // backend could expose this; safe fallback
  const memberSince = profile?.created_at ? fmtDate(profile.created_at) : "—";

  return (
    <div className="space-y-5 pb-4">

      {/* ── Personal Information ── */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 bg-gray-50 border-b border-gray-100">
          <User className="w-4 h-4 text-gray-500" />
          <p className="text-sm font-semibold text-gray-700">Personal Information</p>
        </div>
        <div className="p-4 space-y-4">
          {/* Display name */}
          <div className="space-y-1.5">
            <Label className="text-xs text-gray-600 font-medium flex items-center gap-1">
              <User className="w-3 h-3" />Display Name
            </Label>
            <Input
              placeholder="Your full name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={60}
              className="h-9 text-sm border-gray-300"
            />
            <p className="text-xs text-gray-400">Shown in your account header.</p>
          </div>
          {/* Email */}
          <div className="space-y-1.5">
            <Label className="text-xs text-gray-600 font-medium flex items-center gap-1">
              <Mail className="w-3 h-3" />Email Address
            </Label>
            <Input
              type="email"
              placeholder="your@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-9 text-sm border-gray-300"
            />
            <p className="text-xs text-gray-400">Used for order receipts and PDF delivery.</p>
          </div>
          {/* Mobile (read-only) */}
          <div className="space-y-1.5">
            <Label className="text-xs text-gray-600 font-medium flex items-center gap-1">
              <Phone className="w-3 h-3" />Mobile Number
              <Badge className="ml-1 text-[10px] px-1.5 py-0 bg-gray-100 text-gray-500 border-gray-200">Login ID</Badge>
            </Label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-300" />
              <Input
                value={`+91 ${mobile}`}
                disabled
                className="h-9 text-sm pl-9 bg-gray-50 text-gray-400 border-gray-200 cursor-not-allowed"
              />
            </div>
            <p className="text-xs text-gray-400">Mobile number is your login ID and cannot be changed.</p>
          </div>
          <Button onClick={handleSaveInfo} disabled={savingInfo}
            className="w-full bg-emerald-600 hover:bg-emerald-700 text-white h-9 text-sm">
            {savingInfo ? <><Loader2 className="w-4 h-4 animate-spin mr-1.5" />Saving…</> : <><Check className="w-4 h-4 mr-1.5" />Save Changes</>}
          </Button>
        </div>
      </div>

      {/* ── Security ── */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 bg-gray-50 border-b border-gray-100">
          <Shield className="w-4 h-4 text-gray-500" />
          <p className="text-sm font-semibold text-gray-700">Security</p>
        </div>
        <div className="p-4 space-y-3">
          {[
            { id: "curPw", label: "Current Password", val: currentPw, set: setCurrentPw, show: showCur, toggle: () => setShowCur(v=>!v), ph: "Your current password" },
            { id: "newPw", label: "New Password",     val: newPw,     set: setNewPw,     show: showNew, toggle: () => setShowNew(v=>!v), ph: "Min. 6 characters" },
            { id: "conPw", label: "Confirm New",      val: confirmPw, set: setConfirmPw, show: showCon, toggle: () => setShowCon(v=>!v), ph: "Repeat new password" },
          ].map(({ id, label, val, set, show, toggle, ph }) => (
            <div className="space-y-1.5" key={id}>
              <Label className="text-xs text-gray-600 font-medium">{label}</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                <Input type={show ? "text" : "password"} placeholder={ph} value={val}
                  onChange={(e) => set(e.target.value)}
                  className="h-9 text-sm pl-9 pr-9 border-gray-300" />
                <button type="button" onClick={toggle}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {show ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
          ))}
          <Button onClick={handleChangePassword} disabled={savingPw}
            variant="outline"
            className="w-full border-indigo-200 text-indigo-600 hover:bg-indigo-50 h-9 text-sm mt-1">
            {savingPw ? <><Loader2 className="w-4 h-4 animate-spin mr-1.5" />Updating…</> : <><Lock className="w-4 h-4 mr-1.5" />Change Password</>}
          </Button>
        </div>
      </div>

      {/* ── Account Information ── */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 bg-gray-50 border-b border-gray-100">
          <Settings className="w-4 h-4 text-gray-500" />
          <p className="text-sm font-semibold text-gray-700">Account</p>
        </div>
        <div className="p-4 space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-gray-500 flex items-center gap-1.5">
              <Calendar className="w-3.5 h-3.5" />Member since
            </span>
            <span className="font-medium text-gray-700">{memberSince}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-500">Account status</span>
            <Badge className={profile?.account_status === "active"
              ? "bg-emerald-50 text-emerald-700 border-emerald-200 border text-xs"
              : "bg-amber-50 text-amber-700 border-amber-200 border text-xs"}>
              {profile?.account_status === "active" ? "Active" : "Deletion Pending"}
            </Badge>
          </div>
          {profile?.terms_accepted && (
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Terms accepted</span>
              <span className="text-xs text-gray-400">{fmtDate(profile.terms_accepted_at)}</span>
            </div>
          )}
        </div>
      </div>

      {/* ── Danger Zone ── */}
      <div className="rounded-xl border-2 border-red-100 bg-red-50 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 bg-red-100 border-b border-red-200">
          <AlertTriangle className="w-4 h-4 text-red-500" />
          <p className="text-sm font-semibold text-red-700">Danger Zone</p>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-xs text-red-600">
            Deleting your account will remove all personal data after a 30-day grace period.
            In-flight orders will still be fulfilled. This action cannot be undone.
          </p>
          <Button
            variant="outline"
            onClick={() => { setDeleteConfirm(""); setDeletePw(""); setDeleteDialog(true); }}
            className="w-full border-red-300 text-red-600 hover:bg-red-100 hover:border-red-400 h-9 text-sm"
          >
            <Trash2 className="w-4 h-4 mr-1.5" />Delete My Account
          </Button>
        </div>
      </div>

      {/* ── Delete Account Dialog ── */}
      <AlertDialog open={deleteDialog} onOpenChange={(o) => { if (!o && !deleting) setDeleteDialog(false); }}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-red-600 flex items-center gap-2">
              <AlertTriangle className="w-5 h-5" />Delete Account?
            </AlertDialogTitle>
            <AlertDialogDescription className="space-y-3 text-left">
              <p>This will schedule your account for permanent deletion after 30 days. Your orders will still be fulfilled.</p>
              <p className="text-xs text-gray-500">To cancel, email support@storyme.app within 30 days.</p>
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-gray-700">
                Type <span className="font-mono font-bold text-red-600">DELETE</span> to confirm
              </Label>
              <Input
                placeholder="DELETE"
                value={deleteConfirm}
                onChange={(e) => setDeleteConfirm(e.target.value)}
                className={`border-gray-300 font-mono ${deleteConfirm === "DELETE" ? "border-red-400 bg-red-50" : ""}`}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-gray-700">
                Current password <span className="text-gray-400 font-normal">(if you have one)</span>
              </Label>
              <Input
                type="password"
                placeholder="Your account password"
                value={deletePw}
                onChange={(e) => setDeletePw(e.target.value)}
                className="border-gray-300"
              />
            </div>
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting} onClick={() => setDeleteDialog(false)}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={deleting || deleteConfirm !== "DELETE"}
              onClick={handleDeleteAccount}
              className="bg-red-500 hover:bg-red-600 text-white disabled:opacity-50"
            >
              {deleting
                ? <><Loader2 className="w-4 h-4 animate-spin mr-1" />Deleting…</>
                : "Delete Account"}
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

  const [displayName, setDisplayName] = useState("");
  const [email,       setEmail]       = useState("");

  // Load display name on open
  useEffect(() => {
    if (!open) return;
    axios.get(`${API_V2}/user/profile`, { headers: authHeaders() })
      .then((res) => {
        setDisplayName(res.data.display_name || "");
        setEmail(res.data.email || "");
      })
      .catch(() => {});
  }, [open]);

  const handleSignOut = () => {
    onOpenChange(false);
    clearSession(); stopInactivityTimer(); stopTokenRefresh();
    navigate("/", { replace: true });
  };

  const handleProfileUpdate = (newName, newEmail) => {
    setDisplayName(newName || "");
    setEmail(newEmail || "");
  };

  // Avatar initials
  const initials = displayName
    ? displayName.trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase()
    : mobile.slice(-2);

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
          <div className="flex items-center gap-3 mt-1">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-emerald-400 to-teal-500
              flex items-center justify-center flex-shrink-0 shadow-sm">
              <span className="text-sm font-bold text-white">{initials}</span>
            </div>
            <div>
              {displayName ? (
                <>
                  <p className="text-sm font-semibold text-gray-800 leading-tight">{displayName}</p>
                  <p className="text-xs text-gray-500">+91 {mobile}</p>
                </>
              ) : (
                <p className="text-sm text-gray-600">+91 {mobile}</p>
              )}
              {email && <p className="text-xs text-gray-400">{email}</p>}
            </div>
          </div>
        </SheetHeader>

        {/* ── Tabs ── */}
        <div className="flex-1 overflow-y-auto">
          <Tabs defaultValue="orders" className="h-full flex flex-col">
            <TabsList className="mx-5 mt-4 mb-0 grid grid-cols-3 h-9">
              <TabsTrigger value="orders" className="text-xs">
                <Package className="w-3.5 h-3.5 mr-1" />Orders
              </TabsTrigger>
              <TabsTrigger value="addresses" className="text-xs">
                <MapPin className="w-3.5 h-3.5 mr-1" />Addresses
              </TabsTrigger>
              <TabsTrigger value="profile" className="text-xs">
                <User className="w-3.5 h-3.5 mr-1" />Profile
              </TabsTrigger>
            </TabsList>

            <TabsContent value="orders" className="flex-1 px-5 pt-4 pb-4 mt-0">
              <MyOrdersTab onClose={() => onOpenChange(false)} />
            </TabsContent>
            <TabsContent value="addresses" className="flex-1 px-5 pt-4 pb-4 mt-0">
              <MyAddressesTab />
            </TabsContent>
            <TabsContent value="profile" className="flex-1 px-5 pt-4 pb-4 mt-0">
              <ProfileTab
                mobile={mobile}
                onProfileUpdate={handleProfileUpdate}
                onSignOut={handleSignOut}
              />
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
            <LogOut className="w-4 h-4 mr-2" />Sign Out
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ─── Exported hook for PrintOrderPage address pre-fill ────────────────────────

export function useSavedAddresses() {
  const [addresses, setAddresses] = useState([]);
  const [loading,   setLoading]   = useState(true);

  const fetch = useCallback(() => {
    setLoading(true);
    axios.get(`${API_V2}/user/addresses`, { headers: authHeaders() })
      .then((res) => setAddresses(res.data.addresses || []))
      .catch(() => setAddresses([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetch(); }, [fetch]);
  return { addresses, loading, refetch: fetch };
}
