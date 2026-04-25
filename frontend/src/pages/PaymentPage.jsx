/**
 * PaymentPage.jsx
 * ---------------
 * Unified payment page for all StoryMe purchase flows.
 *
 * Route: /payment  (ProtectedRoute)
 *
 * ── Navigation state shape ────────────────────────────────────────────────────
 *
 * Digital (PDF Download):
 *   { orderType:"pdf_download", generationId, childName, storyId,
 *     storyTitle, totalPages, pdfObjectUrl }
 *
 * Digital (Email PDF):
 *   { orderType:"email_pdf", generationId, childName, storyId,
 *     storyTitle, totalPages }
 *
 * Print:
 *   { orderType:"print", generationId, childName, storyId, storyTitle,
 *     selectedProduct, product, address, saveAddress }
 *
 * ── Pricing principle ─────────────────────────────────────────────────────────
 * Real prices are always shown (₹199 digital / ₹299+ print).
 * During beta the backend records payment_status="beta_bypass" and charges ₹0.
 * The UI shows a "₹0 due today" breakdown so the user understands the real vs
 * beta pricing clearly. This makes migrating to live payments trivial.
 *
 * ── Payment integration roadmap ───────────────────────────────────────────────
 * See docs/payment/PAYMENT_INTEGRATION.md
 */

import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { authHeaders } from "@/lib/session";
import axios from "axios";
import { toast } from "sonner";

import { Button }    from "@/components/ui/button";
import { Input }     from "@/components/ui/input";
import { Label }     from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from "@/components/ui/card";
import {
  ArrowLeft, Loader2, Download, Mail, Printer, BookOpen,
  CreditCard, ShieldCheck, Lock, CheckCircle2, Sparkles, MapPin,
} from "lucide-react";
import AppHeader from "@/components/AppHeader";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_V2      = `${BACKEND_URL}/api/v2`;

// Must mirror backend PDF_DOWNLOAD_PRICE_PAISE / EMAIL_PDF_PRICE_PAISE
const DIGITAL_PRICE_DISPLAY = "₹199";

const ORDER_TYPE_CONFIG = {
  pdf_download: {
    Icon: Download, label: "Digital PDF Download",
    description: "Instant digital PDF — download and keep forever",
    accentColor: "text-indigo-600", accentBg: "bg-indigo-50", accentBorder: "border-indigo-200",
    gradientCls: "from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700",
    price: DIGITAL_PRICE_DISPLAY, showCardForm: false,
  },
  email_pdf: {
    Icon: Mail, label: "Email PDF Delivery",
    description: "PDF sent directly to your inbox",
    accentColor: "text-amber-600", accentBg: "bg-amber-50", accentBorder: "border-amber-200",
    gradientCls: "from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600",
    price: DIGITAL_PRICE_DISPLAY, showCardForm: false,
  },
  print: {
    Icon: Printer, label: "Printed Storybook",
    description: "Premium physical book delivered to your door",
    accentColor: "text-emerald-600", accentBg: "bg-emerald-50", accentBorder: "border-emerald-200",
    gradientCls: "from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700",
    price: null, showCardForm: true,
  },
};

export default function PaymentPage() {
  const navigate = useNavigate();
  const { state = {} } = useLocation();

  const {
    orderType = "pdf_download", generationId = null,
    childName = "Your Child", storyTitle = "Personalised Storybook",
    totalPages = 10, pdfObjectUrl = null,
    selectedProduct = null, product = null, address = null, saveAddress = false,
  } = state;

  const conf      = ORDER_TYPE_CONFIG[orderType] || ORDER_TYPE_CONFIG.pdf_download;
  const { Icon }  = conf;
  const isDigital = orderType === "pdf_download" || orderType === "email_pdf";

  const [placing, setPlacing] = useState(false);
  const [email,   setEmail]   = useState("");

  const priceDisplay = orderType === "print"
    ? (product?.price_display || "₹299")
    : conf.price;

  // ── Guard ─────────────────────────────────────────────────────────────────
  if (!generationId) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-indigo-50 px-4">
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

  // ── Order placement ────────────────────────────────────────────────────────
  const handleConfirmPayment = async () => {
    if (orderType === "email_pdf" && !email.trim()) {
      toast.error("Please enter your email address."); return;
    }
    setPlacing(true);
    try {
      if (isDigital) {
        const res = await axios.post(
          `${API_V2}/orders/digital`,
          { generation_id: generationId, order_type: orderType,
            email: orderType === "email_pdf" ? email.trim() : undefined },
          { headers: authHeaders() },
        );
        const order = res.data;

        if (orderType === "pdf_download" && pdfObjectUrl) {
          const a = document.createElement("a");
          a.href = pdfObjectUrl;
          a.download = `${childName.replace(/\s+/g, "_")}_storybook.pdf`;
          document.body.appendChild(a);
          a.click();
          setTimeout(() => document.body.removeChild(a), 1_000);
          toast.success("Download started! Your order has been recorded.");
        } else if (orderType === "email_pdf") {
          toast.success("Order placed! Your PDF will be emailed shortly.");
        }

        navigate(`/order-status/${order.order_id}`, {
          state: { order, childName, storyId: state.storyId, orderType }, replace: true,
        });

      } else {
        // Print
        if (!selectedProduct || !address) {
          toast.error("Order details missing. Please go back and try again.");
          setPlacing(false); return;
        }
        const res = await axios.post(
          `${API_V2}/orders`,
          {
            generation_id: generationId, product_id: selectedProduct, quantity: 1,
            delivery_address: {
              full_name: address.full_name.trim(), line1: address.line1.trim(),
              line2: address.line2?.trim() || undefined, city: address.city.trim(),
              state: address.state.trim(), pincode: address.pincode.trim(),
              phone: address.phone.trim(), country: "India",
            },
          },
          { headers: authHeaders() },
        );
        const order = res.data;

        if (saveAddress) {
          axios.post(`${API_V2}/user/addresses`, {
            label: "Home", full_name: address.full_name.trim(),
            line1: address.line1.trim(), line2: address.line2?.trim() || null,
            city: address.city.trim(), state: address.state.trim(),
            pincode: address.pincode.trim(), phone: address.phone.trim(), country: "India",
          }, { headers: authHeaders() }).catch(() => {});
        }

        toast.success("Order placed! Your book will be printed and shipped.");
        navigate(`/order-status/${order.order_id}`, {
          state: { order, childName, storyId: state.storyId, orderType }, replace: true,
        });
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to place order. Please try again.");
    } finally {
      setPlacing(false);
    }
  };

  const ctaLabel = placing ? "Processing…"
    : orderType === "pdf_download" ? `Download Now — ${priceDisplay}`
    : orderType === "email_pdf"    ? `Send to Email — ${priceDisplay}`
    : `Confirm Order — ${priceDisplay}`;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50 py-8 px-4">
      <div className="max-w-xl mx-auto">

        <AppHeader />

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
        <Card className={`shadow-md mb-4 border-2 ${conf.accentBorder}`}>
          <CardHeader className={`pb-3 ${conf.accentBg} rounded-t-xl`}>
            <CardTitle className={`text-base flex items-center gap-2 ${conf.accentColor}`}>
              <Icon className="w-5 h-5" />Order Summary
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4 space-y-3">
            <div className="flex items-center gap-3">
              <div className={`w-11 h-11 rounded-xl ${conf.accentBg} flex items-center justify-center flex-shrink-0`}>
                <Icon className={`w-6 h-6 ${conf.accentColor}`} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-gray-800">{conf.label}</p>
                <p className="text-sm text-gray-500">{conf.description}</p>
              </div>
              <div className="text-right flex-shrink-0">
                <p className="text-xl font-black text-gray-900">{priceDisplay}</p>
                {isDigital && <p className="text-xs text-emerald-600 font-medium">Free (Beta)</p>}
              </div>
            </div>

            <Separator />

            <div className={`rounded-xl ${conf.accentBg} px-4 py-3 flex items-start gap-3`}>
              <BookOpen className={`w-5 h-5 ${conf.accentColor} flex-shrink-0 mt-0.5`} />
              <div>
                <p className="text-sm font-semibold text-gray-800">{storyTitle}</p>
                <p className="text-xs text-gray-500">
                  {totalPages} pages · Personalised for {childName}
                  {orderType === "print" && product?.display_name ? ` · ${product.display_name}` : ""}
                </p>
              </div>
            </div>

            {orderType === "print" && address && (
              <div className="rounded-xl bg-gray-50 border border-gray-100 px-4 py-3 flex items-start gap-3">
                <MapPin className="w-4 h-4 text-gray-400 flex-shrink-0 mt-0.5" />
                <div className="text-sm text-gray-700">
                  <p className="font-medium">{address.full_name}</p>
                  <p className="text-xs text-gray-500">
                    {address.line1}{address.line2 ? `, ${address.line2}` : ""},
                    {" "}{address.city}, {address.state} — {address.pincode}
                  </p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Beta notice ── */}
        <div className="rounded-xl bg-gradient-to-r from-emerald-50 to-teal-50 border border-emerald-200 px-4 py-3 mb-4 flex items-start gap-3">
          <Sparkles className="w-5 h-5 text-emerald-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-emerald-800">Beta Period — No payment required right now</p>
            <p className="text-xs text-emerald-700 mt-0.5">
              The listed price of <strong>{priceDisplay}</strong> will apply at public launch.
              For now, {isDigital ? "download is completely free." : "orders are accepted at no charge."}
            </p>
          </div>
        </div>

        {/* ── Email input (email_pdf only) ── */}
        {orderType === "email_pdf" && (
          <Card className="shadow-md mb-4">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Mail className="w-5 h-5 text-amber-500" />Delivery Email
              </CardTitle>
              <CardDescription>We'll send your PDF to this address.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-1.5">
                <Label className="text-gray-700 font-medium">Email Address *</Label>
                <Input type="email" placeholder="your@email.com" value={email}
                  onChange={(e) => setEmail(e.target.value)} className="border-gray-300" autoFocus />
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Dummy card form (print only) ── */}
        {orderType === "print" && (
          <Card className="shadow-md mb-4">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <CreditCard className="w-5 h-5 text-gray-400" />Payment Details
              </CardTitle>
              <CardDescription>Payment integration is coming soon. No charge will be made during beta.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-gray-400">Card Number</Label>
                <Input placeholder="4242 4242 4242 4242" disabled
                  className="border-gray-200 bg-gray-50 text-gray-400 font-mono cursor-not-allowed" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-gray-400">Expiry</Label>
                  <Input placeholder="MM / YY" disabled className="border-gray-200 bg-gray-50 text-gray-400 font-mono cursor-not-allowed" />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-gray-400">CVV</Label>
                  <Input placeholder="•••" disabled className="border-gray-200 bg-gray-50 text-gray-400 font-mono cursor-not-allowed" />
                </div>
              </div>
              <div className="flex items-center gap-4 text-xs text-gray-400">
                <span className="flex items-center gap-1"><ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />256-bit SSL</span>
                <span className="flex items-center gap-1"><Lock className="w-3.5 h-3.5 text-emerald-400" />PCI DSS compliant</span>
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Total + CTA ── */}
        <Card className="shadow-md mb-4 border-2 border-gray-100">
          <CardContent className="pt-5 pb-5 space-y-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-500">Subtotal</span>
                <span className="text-gray-700 font-medium">{priceDisplay}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-emerald-600 font-medium flex items-center gap-1">
                  <Sparkles className="w-3.5 h-3.5" />Beta discount
                </span>
                <span className="text-emerald-600 font-medium">− {priceDisplay}</span>
              </div>
              <Separator />
              <div className="flex items-center justify-between">
                <span className="text-base font-bold text-gray-800">Total due today</span>
                <span className="text-2xl font-black text-emerald-600">₹0</span>
              </div>
            </div>

            <Button
              onClick={handleConfirmPayment}
              disabled={placing || (orderType === "email_pdf" && !email.trim())}
              className={`w-full bg-gradient-to-r ${conf.gradientCls} text-white py-6 text-base font-bold shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {placing ? (
                <><Loader2 className="mr-2 h-5 w-5 animate-spin" />Processing…</>
              ) : orderType === "pdf_download" ? (
                <><Download className="mr-2 h-5 w-5" />{ctaLabel}</>
              ) : orderType === "email_pdf" ? (
                <><Mail className="mr-2 h-5 w-5" />{ctaLabel}</>
              ) : (
                <><CheckCircle2 className="mr-2 h-5 w-5" />{ctaLabel}</>
              )}
            </Button>

            <p className="text-xs text-center text-gray-400">
              By proceeding you agree to our{" "}
              <span className="text-indigo-500 cursor-pointer hover:underline">Terms of Service</span>.
              {isDigital
                ? " You will be charged ₹199 once payment goes live."
                : " You will be charged the listed price once payment goes live."}
            </p>
          </CardContent>
        </Card>

      </div>
    </div>
  );
}
