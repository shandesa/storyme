/**
 * PaymentPage.jsx
 * ---------------
 * Unified dummy payment page for all StoryMe purchase flows.
 *
 * Route: /payment  (ProtectedRoute)
 * Navigation state (from HomePage or PrintOrderPage):
 *
 *   Digital (PDF Download / Email):
 *   {
 *     orderType:    "pdf_download" | "email_pdf",
 *     generationId: string,
 *     childName:    string,
 *     storyId:      string,
 *     storyTitle:   string,
 *     totalPages:   number,
 *     pdfObjectUrl: string | null,   // present for pdf_download only
 *   }
 *
 *   Print (from PrintOrderPage after product + address selection):
 *   {
 *     orderType:       "print",
 *     generationId:    string,
 *     childName:       string,
 *     storyId:         string,
 *     storyTitle:      string,
 *     selectedProduct: string,
 *     product:         object,
 *     address:         object,
 *     saveAddress:     boolean,
 *   }
 *
 * Payment is currently dummy (beta). The form collects inputs but
 * the "Pay" button immediately places the order. When real payment
 * is integrated, this page will send the card/UPI details to the
 * payment gateway and receive a payment_id before placing the order.
 *
 * After successful order placement:
 *   - pdf_download: triggers PDF download then navigates to /order-status/:id
 *   - email_pdf:    navigates to /order-status/:id
 *   - print:        navigates to /order-status/:id
 */

import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { authHeaders } from "@/lib/session";
import axios from "axios";
import { toast } from "sonner";

import { Button }   from "@/components/ui/button";
import { Input }    from "@/components/ui/input";
import { Label }    from "@/components/ui/label";
import { Badge }    from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from "@/components/ui/card";
import {
  ArrowLeft, Loader2, Download, Mail, Printer, BookOpen,
  CreditCard, ShieldCheck, Lock, CheckCircle2,
} from "lucide-react";
import AppHeader from "@/components/AppHeader";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_V2      = `${BACKEND_URL}/api/v2`;

// ─── Order type config ────────────────────────────────────────────────────────

const ORDER_TYPE_CONFIG = {
  pdf_download: {
    icon:        Download,
    label:       "Digital PDF Download",
    description: "Instant digital PDF delivered to your device",
    color:       "text-indigo-600",
    bg:          "bg-indigo-50",
    border:      "border-indigo-200",
    badgeColor:  "bg-indigo-100 text-indigo-700",
    price:       "Free (Beta)",
  },
  email_pdf: {
    icon:        Mail,
    label:       "Email PDF Delivery",
    description: "PDF sent directly to your inbox",
    color:       "text-amber-600",
    bg:          "bg-amber-50",
    border:      "border-amber-200",
    badgeColor:  "bg-amber-100 text-amber-700",
    price:       "Free (Beta)",
  },
  print: {
    icon:        Printer,
    label:       "Printed Storybook",
    description: "Premium physical book delivered to your door",
    color:       "text-emerald-600",
    bg:          "bg-emerald-50",
    border:      "border-emerald-200",
    badgeColor:  "bg-emerald-100 text-emerald-700",
    price:       null,   // comes from product
  },
};

// ─── Component ────────────────────────────────────────────────────────────────

export default function PaymentPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const state = location.state || {};
  const {
    orderType     = "pdf_download",
    generationId  = null,
    childName     = "Your Child",
    storyTitle    = "Personalised Storybook",
    totalPages    = 10,
    pdfObjectUrl  = null,
    // print-specific
    selectedProduct = null,
    product         = null,
    address         = null,
    saveAddress     = false,
  } = state;

  const typeConf = ORDER_TYPE_CONFIG[orderType] || ORDER_TYPE_CONFIG.pdf_download;
  const TypeIcon = typeConf.icon;

  const [placing, setPlacing] = useState(false);
  // Dummy payment fields — collected but not actually sent anywhere yet
  const [email,   setEmail]   = useState("");

  // ── Guard ─────────────────────────────────────────────────────────────────

  if (!generationId) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-amber-50 to-emerald-50 px-4">
        <Card className="max-w-sm w-full shadow-lg">
          <CardContent className="pt-8 pb-8 text-center space-y-4">
            <p className="text-red-500">No order context found. Please generate a storybook first.</p>
            <Button onClick={() => navigate("/home")} variant="outline">
              <ArrowLeft className="mr-2 h-4 w-4" />Back to Home
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ── Place order ────────────────────────────────────────────────────────────

  const handleConfirmPayment = async () => {
    setPlacing(true);
    try {
      if (orderType === "pdf_download" || orderType === "email_pdf") {
        // ── Digital order ─────────────────────────────────────────────────
        const res = await axios.post(
          `${API_V2}/orders/digital`,
          {
            generation_id: generationId,
            order_type:    orderType,
            email:         orderType === "email_pdf" ? email : undefined,
          },
          { headers: authHeaders() },
        );
        const order = res.data;

        toast.success(
          orderType === "pdf_download"
            ? "Payment confirmed! Downloading your PDF…"
            : "Order placed! PDF will be emailed shortly.",
        );

        // Trigger browser download for pdf_download
        if (orderType === "pdf_download" && pdfObjectUrl) {
          const link = document.createElement("a");
          link.href     = pdfObjectUrl;
          link.download = `${childName.replace(/\s+/g, "_")}_storybook.pdf`;
          document.body.appendChild(link);
          link.click();
          setTimeout(() => document.body.removeChild(link), 1000);
        }

        navigate(`/order-status/${order.order_id}`, {
          state: { order, childName, storyId: state.storyId, orderType },
          replace: true,
        });

      } else if (orderType === "print") {
        // ── Print order ───────────────────────────────────────────────────
        if (!selectedProduct || !address) {
          toast.error("Order details missing. Please go back and try again.");
          setPlacing(false);
          return;
        }

        const payload = {
          generation_id:    generationId,
          product_id:       selectedProduct,
          quantity:         1,
          delivery_address: {
            full_name: address.full_name.trim(),
            line1:     address.line1.trim(),
            line2:     address.line2?.trim() || undefined,
            city:      address.city.trim(),
            state:     address.state.trim(),
            pincode:   address.pincode.trim(),
            phone:     address.phone.trim(),
            country:   "India",
          },
        };

        const res = await axios.post(`${API_V2}/orders`, payload, { headers: authHeaders() });
        const order = res.data;

        // Optionally save address to address book
        if (saveAddress) {
          try {
            await axios.post(
              `${API_V2}/user/addresses`,
              {
                label:    "Home",
                full_name: address.full_name.trim(),
                line1:    address.line1.trim(),
                line2:    address.line2?.trim() || null,
                city:     address.city.trim(),
                state:    address.state.trim(),
                pincode:  address.pincode.trim(),
                phone:    address.phone.trim(),
                country:  "India",
              },
              { headers: authHeaders() },
            );
          } catch { /* non-fatal */ }
        }

        toast.success("Order placed successfully!");
        navigate(`/order-status/${order.order_id}`, {
          state: { order, childName, storyId: state.storyId, orderType },
          replace: true,
        });
      }
    } catch (err) {
      const detail = err.response?.data?.detail || "Failed to place order. Please try again.";
      toast.error(detail);
    } finally {
      setPlacing(false);
    }
  };

  const priceDisplay = orderType === "print"
    ? (product?.price_display || "₹299")
    : typeConf.price;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50 py-8 px-4">
      <div className="max-w-xl mx-auto">

        <AppHeader />

        {/* Sub-header */}
        <div className="flex items-center gap-3 mb-6 -mt-2">
          <Button variant="ghost" size="sm" onClick={() => navigate(-1)}
            className="text-gray-500 hover:text-gray-700 -ml-2">
            <ArrowLeft className="w-4 h-4 mr-1" />Back
          </Button>
          <div className="flex items-center gap-2">
            <Lock className="w-5 h-5 text-indigo-500" />
            <h1 className="text-xl font-bold text-gray-900">Secure Checkout</h1>
          </div>
        </div>

        {/* ── Order summary ── */}
        <Card className={`shadow-md mb-5 border ${typeConf.border}`}>
          <CardHeader className={`pb-3 ${typeConf.bg} rounded-t-lg`}>
            <CardTitle className="text-base flex items-center gap-2">
              <TypeIcon className={`w-5 h-5 ${typeConf.color}`} />
              Order Summary
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4 space-y-3">
            <div className="flex items-start gap-3">
              <div className={`w-10 h-10 rounded-lg ${typeConf.bg} flex items-center justify-center flex-shrink-0`}>
                <TypeIcon className={`w-5 h-5 ${typeConf.color}`} />
              </div>
              <div className="flex-1">
                <p className="font-semibold text-gray-800">{typeConf.label}</p>
                <p className="text-sm text-gray-500">{typeConf.description}</p>
              </div>
              <p className="text-lg font-black text-gray-800">{priceDisplay}</p>
            </div>

            <Separator />

            {/* Storybook details */}
            <div className={`rounded-lg ${typeConf.bg} px-4 py-3 flex items-center gap-3`}>
              <BookOpen className={`w-5 h-5 ${typeConf.color} flex-shrink-0`} />
              <div>
                <p className={`text-sm font-semibold ${typeConf.color.replace("600", "800")}`}>
                  {storyTitle}
                </p>
                <p className="text-xs text-gray-500">
                  {totalPages} pages · Personalised for {childName}
                  {orderType === "print" && product?.display_name ? ` · ${product.display_name}` : ""}
                </p>
              </div>
            </div>

            {/* Delivery address summary (print only) */}
            {orderType === "print" && address && (
              <div className="rounded-lg bg-gray-50 border border-gray-100 px-4 py-3 text-sm text-gray-700 space-y-0.5">
                <p className="font-semibold text-gray-800 text-xs uppercase tracking-wide text-gray-500 mb-1">
                  Shipping to
                </p>
                <p className="font-medium">{address.full_name}</p>
                <p className="text-xs text-gray-500">
                  {address.line1}{address.line2 ? `, ${address.line2}` : ""}<br />
                  {address.city}, {address.state} — {address.pincode}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Beta notice ── */}
        <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 mb-5 flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-blue-700">
            <strong>Beta Period:</strong> All orders are currently free of charge.
            Payment integration is coming soon — your details are collected for testing only
            and will not be charged.
          </p>
        </div>

        {/* ── Payment form (dummy) ── */}
        <Card className="shadow-md mb-5">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <CreditCard className="w-5 h-5 text-gray-500" />
              Payment Details
            </CardTitle>
            <CardDescription>
              Enter your payment details below. No charges will be made during the beta period.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">

            {orderType === "email_pdf" && (
              <div className="space-y-1.5">
                <Label className="text-gray-700 font-medium">Email Address *</Label>
                <Input
                  type="email"
                  placeholder="your@email.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="border-gray-300"
                />
                <p className="text-xs text-gray-400">The PDF will be sent to this address.</p>
              </div>
            )}

            {/* Dummy card fields */}
            <div className="space-y-1.5">
              <Label className="text-gray-700 font-medium">Card Number</Label>
              <Input
                placeholder="4242 4242 4242 4242"
                maxLength={19}
                className="border-gray-300 font-mono"
                disabled
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-gray-700 font-medium">Expiry</Label>
                <Input placeholder="MM / YY" className="border-gray-300 font-mono" disabled />
              </div>
              <div className="space-y-1.5">
                <Label className="text-gray-700 font-medium">CVV</Label>
                <Input placeholder="•••" maxLength={4} className="border-gray-300 font-mono" disabled />
              </div>
            </div>

            {/* Trust badges */}
            <div className="flex items-center gap-4 text-xs text-gray-400 pt-1">
              <div className="flex items-center gap-1">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>256-bit SSL</span>
              </div>
              <div className="flex items-center gap-1">
                <Lock className="w-4 h-4 text-emerald-400" />
                <span>PCI DSS compliant</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* ── CTA ── */}
        <Card className="shadow-md mb-4 border-indigo-100">
          <CardContent className="pt-5 space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-600 font-medium">Total</span>
              <span className="text-2xl font-black text-gray-900">{priceDisplay}</span>
            </div>

            <Button
              onClick={handleConfirmPayment}
              disabled={placing || (orderType === "email_pdf" && !email.trim())}
              className="w-full bg-gradient-to-r from-indigo-500 to-purple-600
                hover:from-indigo-600 hover:to-purple-700
                text-white py-6 text-base font-bold shadow-lg
                disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {placing ? (
                <><Loader2 className="mr-2 h-5 w-5 animate-spin" />Processing…</>
              ) : (
                <><Lock className="mr-2 h-5 w-5" />
                  {orderType === "print"
                    ? `Confirm Order — ${priceDisplay}`
                    : `Complete Purchase — ${priceDisplay}`}
                </>
              )}
            </Button>

            <p className="text-xs text-center text-gray-400">
              By completing this purchase you agree to our{" "}
              <span className="text-indigo-500 cursor-pointer">Terms of Service</span>.
              No card will be charged during the beta period.
            </p>
          </CardContent>
        </Card>

      </div>
    </div>
  );
}
