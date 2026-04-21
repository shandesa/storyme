/**
 * PrintOrderPage.jsx
 * ------------------
 * Full-page print order flow.
 *
 * Route: /print-order
 * Navigation state (from HomePage):
 *   { generationId, childName, storyId, pdfBlobPath }
 *
 * Flow:
 *   1. Load products from /api/v2/print/products
 *   2. User selects paperback or hardcover
 *   3. User fills delivery address (all fields required)
 *   4. POST /api/v2/orders → receive order_id
 *   5. Navigate to /order-status/:orderId (confirmation screen)
 *
 * Architecture notes:
 *   - No state stored in localStorage; all data in React state
 *   - generationId links to backend GenerationSession for PDF retrieval
 *   - X-User-Mobile header sent if mobile is in session storage (set by auth)
 *   - Beta notice shown — payment not yet wired
 */

import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button }   from "@/components/ui/button";
import { Input }    from "@/components/ui/input";
import { Label }    from "@/components/ui/label";
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Badge }     from "@/components/ui/badge";
import {
  ArrowLeft, Loader2, Printer, ShieldCheck, Truck, BookOpen,
} from "lucide-react";
import PrintProductCard from "@/components/PrintProductCard";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_V2      = `${BACKEND_URL}/api/v2`;

// Indian states for dropdown
const INDIAN_STATES = [
  "Andhra Pradesh","Arunachal Pradesh","Assam","Bihar","Chhattisgarh",
  "Goa","Gujarat","Haryana","Himachal Pradesh","Jharkhand","Karnataka",
  "Kerala","Madhya Pradesh","Maharashtra","Manipur","Meghalaya","Mizoram",
  "Nagaland","Odisha","Punjab","Rajasthan","Sikkim","Tamil Nadu","Telangana",
  "Tripura","Uttar Pradesh","Uttarakhand","West Bengal",
  "Andaman and Nicobar Islands","Chandigarh","Dadra and Nagar Haveli",
  "Daman and Diu","Delhi","Jammu and Kashmir","Ladakh","Lakshadweep","Puducherry",
];

export default function PrintOrderPage() {
  const navigate  = useNavigate();
  const location  = useLocation();

  // State passed from HomePage
  const {
    generationId,
    childName    = "Your Child",
    storyId      = "forest_of_smiles",
    pdfBlobPath  = null,
  } = location.state || {};

  const [products,         setProducts]         = useState([]);
  const [productsLoading,  setProductsLoading]  = useState(true);
  const [selectedProduct,  setSelectedProduct]  = useState(null);
  const [placing,          setPlacing]          = useState(false);

  const [address, setAddress] = useState({
    full_name: childName !== "Your Child" ? "" : "",
    line1:     "",
    line2:     "",
    city:      "",
    state:     "",
    pincode:   "",
    phone:     "",
  });

  const [errors, setErrors] = useState({});

  // ── Load products ──────────────────────────────────────────────────────────

  useEffect(() => {
    axios.get(`${API_V2}/print/products`)
      .then((res) => {
        const prods = res.data.products || [];
        setProducts(prods);
        if (prods.length > 0) setSelectedProduct(prods[0].product_id);
      })
      .catch(() => toast.error("Failed to load print options. Please refresh."))
      .finally(() => setProductsLoading(false));
  }, []);

  // ── Redirect if no generation session ─────────────────────────────────────

  useEffect(() => {
    if (!generationId) {
      toast.error("No generation session found. Please generate a storybook first.");
      navigate("/home");
    }
  }, [generationId, navigate]);

  // ── Validation ─────────────────────────────────────────────────────────────

  const validate = () => {
    const e = {};
    if (!address.full_name?.trim())                  e.full_name = "Full name is required";
    if (!address.line1?.trim())                      e.line1     = "Address is required";
    if (!address.city?.trim())                       e.city      = "City is required";
    if (!address.state?.trim())                      e.state     = "State is required";
    if (!/^\d{6}$/.test(address.pincode))            e.pincode   = "Enter a valid 6-digit pincode";
    if (!/^\d{10}$/.test(address.phone))             e.phone     = "Enter a valid 10-digit mobile number";
    if (!selectedProduct)                            e.product   = "Please select a print option";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleAddressChange = (field, value) => {
    setAddress((prev) => ({ ...prev, [field]: value }));
    if (errors[field]) setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  // ── Place order ────────────────────────────────────────────────────────────

  const handlePlaceOrder = async () => {
    if (!validate()) {
      toast.error("Please fix the highlighted fields.");
      return;
    }

    setPlacing(true);
    try {
      // Get user mobile from session (set by auth flow)
      const userMobile = sessionStorage.getItem("user_mobile") || "";

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

      const headers = {};
      if (userMobile) headers["X-User-Mobile"] = userMobile;

      const res = await axios.post(`${API_V2}/orders`, payload, { headers });
      const order = res.data;

      toast.success("Order placed successfully!");

      navigate(`/order-status/${order.order_id}`, {
        state: { order, childName, storyId },
      });

    } catch (err) {
      const detail = err.response?.data?.detail || "Failed to place order. Please try again.";
      toast.error(detail);
    } finally {
      setPlacing(false);
    }
  };

  // ── Selected product details ───────────────────────────────────────────────

  const product = products.find((p) => p.product_id === selectedProduct);
  const priceDisplay = product?.price_display || "";

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-white to-emerald-50 py-8 px-4">
      <div className="max-w-2xl mx-auto">

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <Button variant="ghost" size="sm" onClick={() => navigate("/home")}
            className="text-gray-500 hover:text-gray-700 -ml-2">
            <ArrowLeft className="w-4 h-4 mr-1" />Back
          </Button>
          <div className="flex items-center gap-2">
            <Printer className="w-7 h-7 text-amber-500" />
            <h1 className="text-2xl font-bold text-gray-900">Order a Printed Copy</h1>
          </div>
        </div>

        {/* Story context banner */}
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-3 mb-5 flex items-center gap-3">
          <BookOpen className="w-5 h-5 text-emerald-600 flex-shrink-0" />
          <div>
            <p className="text-sm font-semibold text-emerald-800">
              Storybook for <span className="text-emerald-600">{childName}</span>
            </p>
            <p className="text-xs text-emerald-600">
              Forest of Smiles · 10 pages · Full colour · Personalised
            </p>
          </div>
        </div>

        {/* ── Product selection ── */}
        <Card className="shadow-md mb-5">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">Choose Your Format</CardTitle>
            <CardDescription>
              Select paperback or hardcover — both include all 10 personalised story pages.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {productsLoading ? (
              <div className="flex items-center justify-center py-12 gap-3 text-gray-400">
                <Loader2 className="w-6 h-6 animate-spin" />
                <span>Loading print options…</span>
              </div>
            ) : products.length === 0 ? (
              <p className="text-center text-gray-500 py-8">No print options available. Please try again later.</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {products.map((p) => (
                  <PrintProductCard
                    key={p.product_id}
                    product={p}
                    selected={selectedProduct === p.product_id}
                    onSelect={setSelectedProduct}
                    backendUrl={BACKEND_URL}
                  />
                ))}
              </div>
            )}
            {errors.product && (
              <p className="text-red-500 text-xs mt-2">{errors.product}</p>
            )}
          </CardContent>
        </Card>

        {/* ── Delivery address ── */}
        <Card className="shadow-md mb-5">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">Delivery Address</CardTitle>
            <CardDescription>
              Your printed storybook will be shipped to this address.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">

            <div className="space-y-1.5">
              <Label className="text-gray-700 font-medium">Full Name *</Label>
              <Input
                placeholder="Recipient's full name"
                value={address.full_name}
                onChange={(e) => handleAddressChange("full_name", e.target.value)}
                className={errors.full_name ? "border-red-400" : "border-gray-300"}
              />
              {errors.full_name && <p className="text-red-500 text-xs">{errors.full_name}</p>}
            </div>

            <div className="space-y-1.5">
              <Label className="text-gray-700 font-medium">Phone Number *</Label>
              <Input
                placeholder="10-digit mobile number"
                value={address.phone}
                maxLength={10}
                onChange={(e) => handleAddressChange("phone", e.target.value.replace(/\D/g,""))}
                className={errors.phone ? "border-red-400" : "border-gray-300"}
              />
              {errors.phone && <p className="text-red-500 text-xs">{errors.phone}</p>}
            </div>

            <div className="space-y-1.5">
              <Label className="text-gray-700 font-medium">Address Line 1 *</Label>
              <Input
                placeholder="House/flat no., building, street"
                value={address.line1}
                onChange={(e) => handleAddressChange("line1", e.target.value)}
                className={errors.line1 ? "border-red-400" : "border-gray-300"}
              />
              {errors.line1 && <p className="text-red-500 text-xs">{errors.line1}</p>}
            </div>

            <div className="space-y-1.5">
              <Label className="text-gray-700 font-medium">Address Line 2</Label>
              <Input
                placeholder="Area, landmark (optional)"
                value={address.line2}
                onChange={(e) => handleAddressChange("line2", e.target.value)}
                className="border-gray-300"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-gray-700 font-medium">City *</Label>
                <Input
                  placeholder="City"
                  value={address.city}
                  onChange={(e) => handleAddressChange("city", e.target.value)}
                  className={errors.city ? "border-red-400" : "border-gray-300"}
                />
                {errors.city && <p className="text-red-500 text-xs">{errors.city}</p>}
              </div>
              <div className="space-y-1.5">
                <Label className="text-gray-700 font-medium">Pincode *</Label>
                <Input
                  placeholder="6-digit pincode"
                  value={address.pincode}
                  maxLength={6}
                  onChange={(e) => handleAddressChange("pincode", e.target.value.replace(/\D/g,""))}
                  className={errors.pincode ? "border-red-400" : "border-gray-300"}
                />
                {errors.pincode && <p className="text-red-500 text-xs">{errors.pincode}</p>}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-gray-700 font-medium">State *</Label>
              <select
                value={address.state}
                onChange={(e) => handleAddressChange("state", e.target.value)}
                className={`w-full rounded-md border px-3 py-2 text-sm bg-white text-gray-900
                  focus:outline-none focus:ring-2 focus:ring-emerald-400
                  ${errors.state ? "border-red-400" : "border-gray-300"}`}
              >
                <option value="">Select state</option>
                {INDIAN_STATES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              {errors.state && <p className="text-red-500 text-xs">{errors.state}</p>}
            </div>

          </CardContent>
        </Card>

        {/* ── Order summary + CTA ── */}
        <Card className="shadow-md mb-5 border-amber-200">
          <CardContent className="pt-5 space-y-4">

            <div className="flex items-center justify-between">
              <div>
                <p className="font-semibold text-gray-800">
                  {product?.display_name || "Select a format"}
                </p>
                <p className="text-sm text-gray-500">Qty: 1 · Personalised for {childName}</p>
              </div>
              <p className="text-2xl font-black text-amber-600">{priceDisplay}</p>
            </div>

            <Separator />

            {/* Beta notice */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2.5">
              <p className="text-xs text-blue-700 font-medium">
                🎉 Beta Period — Orders are being accepted at no charge.
                Payment integration coming soon. Your book will be printed and shipped free of cost.
              </p>
            </div>

            {/* Trust badges */}
            <div className="flex items-center gap-4 text-xs text-gray-500">
              <div className="flex items-center gap-1">
                <ShieldCheck className="w-4 h-4 text-emerald-500" />
                <span>Secure order</span>
              </div>
              <div className="flex items-center gap-1">
                <Truck className="w-4 h-4 text-emerald-500" />
                <span>7–14 business days</span>
              </div>
              <div className="flex items-center gap-1">
                <BookOpen className="w-4 h-4 text-emerald-500" />
                <span>Quality guaranteed</span>
              </div>
            </div>

            <Button
              onClick={handlePlaceOrder}
              disabled={placing || productsLoading || !selectedProduct}
              className="w-full bg-amber-500 hover:bg-amber-600 text-white py-6 text-base font-bold shadow-md"
            >
              {placing ? (
                <><Loader2 className="mr-2 h-5 w-5 animate-spin" />Placing Order…</>
              ) : (
                <><Printer className="mr-2 h-5 w-5" />Place Order — {priceDisplay || "Select format"}</>
              )}
            </Button>

            <p className="text-xs text-center text-gray-400">
              By placing an order you agree to our terms. You will receive order confirmation via the app.
            </p>
          </CardContent>
        </Card>

      </div>
    </div>
  );
}
