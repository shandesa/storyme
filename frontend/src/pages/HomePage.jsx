/**
 * HomePage.jsx — StoryMe main generation flow
 *
 * Step machine:
 *   INPUT → PREVIEWING → PREVIEW → GENERATING → COMPLETE → PRINT_OPTIONS
 *
 * After PDF downloads automatically at COMPLETE, user sees two choices:
 *   [Download PDF Again]  [Order a Printed Copy →]
 *
 * The generation_id returned in X-Generation-ID response header is stored
 * in state and passed to PrintOrderPage via React Router navigation state.
 * Nothing is stored in localStorage/sessionStorage.
 */

import { useState, useEffect } from "react";
import { clearSession, stopInactivityTimer, stopTokenRefresh } from "@/lib/session";
import axios from "axios";
import { Button }   from "@/components/ui/button";
import { Input }    from "@/components/ui/input";
import { Label }    from "@/components/ui/label";
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Badge }  from "@/components/ui/badge";
import { toast }  from "sonner";
import {
  Loader2, Upload, BookOpen, Sparkles, ChevronRight,
  X, Download, RefreshCw, LogOut, Printer, CheckCircle, Mail,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import AppHeader from "@/components/AppHeader";

// ─── API ────────────────────────────────────────────────────────────────────

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_V2      = `${BACKEND_URL}/api/v2`;
const API_V1      = `${BACKEND_URL}/api`;

const PREVIEW_TIMEOUT_MS  =  120_000;
const GENERATE_TIMEOUT_MS =  600_000;

// ─── Steps ──────────────────────────────────────────────────────────────────

const STEPS = {
  INPUT:         "input",
  PREVIEWING:    "previewing",
  PREVIEW:       "preview",
  GENERATING:    "generating",
  COMPLETE:      "complete",
  PRINT_OPTIONS: "print_options",   // NEW — shown after PDF download
};

// ─── Generation mode options ─────────────────────────────────────────────────
const GENERATION_MODES = [
  { value: "opencv", label: "Classic Storybook",
    description: "Fast face personalisation using computer vision (recommended)" },
  { value: "ai",     label: "AI-Powered Storybook",
    description: "AI generates each scene — slower but highly creative" },
];

// ─── Gender options ──────────────────────────────────────────────────────────
const GENDER_OPTIONS = [
  { value: "neutral", label: "Neutral" },
  { value: "male",    label: "Boy"     },
  { value: "female",  label: "Girl"    },
];

// ─── Component ───────────────────────────────────────────────────────────────

export default function HomePage() {
  const navigate = useNavigate();

  const [step, setStep]                 = useState(STEPS.INPUT);
  const [childName, setChildName]       = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl]     = useState(null);
  const [stories, setStories]           = useState([]);
  const [selectedStory, setSelectedStory]   = useState("forest_of_smiles");
  const [generationMode, setGenerationMode] = useState("opencv");
  const [gender, setGender]                 = useState("neutral");
  const [previewImage, setPreviewImage]     = useState(null);
  const [pdfBlob, setPdfBlob]               = useState(null);
  const [pdfObjectUrl, setPdfObjectUrl]     = useState(null);
  const [statusMessage, setStatusMessage]   = useState("");
  const [totalPages, setTotalPages]         = useState(0);
  // NEW: store generation metadata for print ordering
  const [generationId, setGenerationId]     = useState(null);
  const [storyId, setStoryId]               = useState(null);

  useEffect(() => {
    axios.get(`${API_V2}/stories`)
      .then((res) => setStories(res.data.stories || []))
      .catch(() => {});
  }, []);

  // ── File handling ──────────────────────────────────────────────────────────

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!["image/jpeg","image/jpg","image/png","image/webp"].includes(file.type)) {
      toast.error("Please upload a valid image (JPG, PNG, or WEBP)");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error("File size must be less than 5MB");
      return;
    }
    setSelectedFile(file);
    const reader = new FileReader();
    reader.onloadend = () => setPreviewUrl(reader.result);
    reader.readAsDataURL(file);
  };

  // ── Preview ────────────────────────────────────────────────────────────────

  const handlePreview = async (e) => {
    e.preventDefault();
    if (!childName.trim()) { toast.error("Please enter your child's name"); return; }
    if (!selectedFile)     { toast.error("Please upload a photo"); return; }

    setStep(STEPS.PREVIEWING);
    setStatusMessage("Generating preview of page 1…");

    try {
      const formData = new FormData();
      formData.append("name",     childName.trim());
      formData.append("image",    selectedFile);
      formData.append("story_id", selectedStory);
      formData.append("mode",     generationMode);
      formData.append("gender",   gender);

      const res = await axios.post(`${API_V2}/generate/preview`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: PREVIEW_TIMEOUT_MS,
      });

      const story = stories.find((s) => s.story_id === selectedStory);
      setTotalPages(story?.total_pages || 10);
      setStoryId(selectedStory);
      setPreviewImage(res.data.preview_image);
      setStep(STEPS.PREVIEW);
      toast.success("Preview ready — review page 1 and proceed.");
    } catch (err) {
      console.error("Preview failed:", err);
      toast.error(err.response?.data?.detail || "Preview generation failed");
      setStep(STEPS.INPUT);
    }
  };

  // ── Full generation ────────────────────────────────────────────────────────

  const handleProceed = async () => {
    if (!selectedFile || !childName.trim()) {
      toast.error("Missing photo or name — please start over.");
      setStep(STEPS.INPUT);
      return;
    }

    setStep(STEPS.GENERATING);
    const modeLabel = GENERATION_MODES.find((m) => m.value === generationMode)?.label || generationMode;
    setStatusMessage(`Generating your personalised storybook using ${modeLabel}…`);

    try {
      const formData = new FormData();
      formData.append("name",     childName.trim());
      formData.append("image",    selectedFile);
      formData.append("story_id", selectedStory);
      formData.append("mode",     generationMode);
      formData.append("gender",   gender);

      const res = await axios.post(`${API_V1}/generate`, formData, {
        headers:      { "Content-Type": "multipart/form-data" },
        responseType: "blob",
        timeout:      GENERATE_TIMEOUT_MS,
      });

      // ── Read X-Generation-ID from response headers ─────────────────────────
      // The backend sets this header so we can link the PDF to an order later.
      // axios exposes custom headers when CORS expose_headers is configured.
      const genId = res.headers["x-generation-id"] || null;
      const sid   = res.headers["x-story-id"]      || selectedStory;
      setGenerationId(genId);
      setStoryId(sid);

      const blob = new Blob([res.data], { type: "application/pdf" });
      setPdfBlob(blob);
      // Create a stable object URL for use in PaymentPage (no auto-download)
      const objUrl = window.URL.createObjectURL(blob);
      setPdfObjectUrl(objUrl);

      setStep(STEPS.COMPLETE);
      setStatusMessage("Your storybook is ready!");
      toast.success("Storybook generated! Choose how you'd like to get it below.");
    } catch (err) {
      console.error("Full generation failed:", err);
      let detail = "Generation failed. Please try again.";
      if (err.response?.data instanceof Blob) {
        try {
          const text = await err.response.data.text();
          const json = JSON.parse(text);
          detail = json.detail || detail;
        } catch { /* ignore */ }
      } else if (err.response?.data?.detail) {
        detail = err.response.data.detail;
      } else if (err.code === "ECONNABORTED") {
        detail = "Generation timed out — please try again.";
      }
      toast.error(detail);
      setStep(STEPS.PREVIEW);
    }
  };

  // ── Download ────────────────────────────────────────────────────────────────

  const handleDownload = () => {
    if (!pdfBlob) { toast.error("PDF not available — please generate again."); return; }
    _downloadBlob(pdfBlob, `${childName.replace(/\s+/g, "_")}_storybook.pdf`);
  };

  const _downloadBlob = (blob, filename) => {
    const url  = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = filename;
    document.body.appendChild(link);
    link.click();
    setTimeout(() => { document.body.removeChild(link); window.URL.revokeObjectURL(url); }, 1000);
  };

  // ── Navigate to print order ────────────────────────────────────────────────

  const handleOrderPrint = () => {
    navigate("/print-order", {
      state: {
        generationId,
        childName:   childName.trim(),
        storyId:     storyId || selectedStory,
        pdfBlobPath: null,   // blob_path comes from session_store on backend
      },
    });
  };

  // ── Reset ──────────────────────────────────────────────────────────────────

  const handleCancel = () => {
    setStep(STEPS.INPUT); setPreviewImage(null); setPdfBlob(null);
  };

  const resetAll = () => {
    if (pdfObjectUrl) window.URL.revokeObjectURL(pdfObjectUrl);
    setStep(STEPS.INPUT); setChildName(""); setSelectedFile(null);
    setPreviewUrl(null); setPreviewImage(null); setPdfBlob(null);
    setPdfObjectUrl(null); setTotalPages(0); setStatusMessage("");
    setGenerationId(null); setStoryId(null);
  };

  const handleLogout = () => {
    clearSession();
    stopInactivityTimer();
    stopTokenRefresh();
    navigate("/", { replace: true });
  };

  const selectedStoryTitle =
    stories.find((s) => s.story_id === selectedStory)
      ?.title?.replace("{name}", childName || "Your Child") || "Forest of Smiles";

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-white to-emerald-50 py-8 px-4">
      <div className="max-w-2xl mx-auto">

        {/* Header */}
        <AppHeader />
        <p className="text-base text-gray-500 text-center mb-6">AI-powered personalised storybooks for your child</p>

        {/* ── INPUT ── */}
        {step === STEPS.INPUT && (
          <Card className="shadow-lg border-emerald-100">
            <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-4">
              <CardTitle className="text-xl text-gray-800">Create Your Story</CardTitle>
              <CardDescription>Upload a photo and choose a story to begin</CardDescription>
            </CardHeader>
            <CardContent className="pt-5">
              <form onSubmit={handlePreview} className="space-y-5">
                <div className="space-y-1.5">
                  <Label className="text-gray-700 font-medium">Story</Label>
                  <Select value={selectedStory} onValueChange={setSelectedStory}>
                    <SelectTrigger className="border-gray-300"><SelectValue placeholder="Select a story" /></SelectTrigger>
                    <SelectContent>
                      {stories.map((s) => (
                        <SelectItem key={s.story_id} value={s.story_id}>
                          {s.title.replace("{name}", "Your Child")} ({s.total_pages} pages)
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <Label className="text-gray-700 font-medium">Generation Style</Label>
                  <Select value={generationMode} onValueChange={setGenerationMode}>
                    <SelectTrigger className="border-gray-300"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {GENERATION_MODES.map((m) => (
                        <SelectItem key={m.value} value={m.value}>
                          <div>
                            <span className="font-medium">{m.label}</span>
                            <span className="text-xs text-gray-500 ml-2">{m.description}</span>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <Label className="text-gray-700 font-medium">Character Style</Label>
                  <Select value={gender} onValueChange={setGender}>
                    <SelectTrigger className="border-gray-300"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {GENDER_OPTIONS.map((g) => (
                        <SelectItem key={g.value} value={g.value}>{g.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="childName" className="text-gray-700 font-medium">Child's Name</Label>
                  <Input id="childName"
                    placeholder="Enter your child's name" value={childName}
                    onChange={(e) => setChildName(e.target.value)} className="border-gray-300" />
                </div>

                <div className="space-y-1.5">
                  <Label className="text-gray-700 font-medium">Upload Photo</Label>
                  <div className="border-2 border-dashed border-gray-300 rounded-lg p-5 text-center hover:border-emerald-400 transition-colors">
                    {previewUrl ? (
                      <div className="space-y-3">
                        <img src={previewUrl} alt="Preview"
                          className="w-28 h-28 object-cover rounded-full mx-auto border-4 border-emerald-200" />
                        <Button type="button" variant="outline" size="sm"
                          onClick={() => { setSelectedFile(null); setPreviewUrl(null); }}>
                          Remove Photo
                        </Button>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        <Upload className="w-10 h-10 text-gray-400 mx-auto" />
                        <Label htmlFor="photoUpload"
                          className="cursor-pointer text-emerald-600 hover:text-emerald-700 font-medium">
                          Click to upload
                        </Label>
                        <p className="text-xs text-gray-500">PNG, JPG, WEBP — Max 5MB</p>
                      </div>
                    )}
                    <input id="photoUpload" type="file"
                      accept="image/jpeg,image/jpg,image/png,image/webp"
                      onChange={handleFileChange} className="hidden" />
                  </div>
                </div>

                <Button type="submit"
                  className="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-5 text-base font-semibold">
                  <Sparkles className="mr-2 h-4 w-4" />Generate Preview
                </Button>
              </form>
            </CardContent>
          </Card>
        )}

        {/* ── PREVIEWING ── */}
        {step === STEPS.PREVIEWING && (
          <Card className="shadow-lg">
            <CardContent className="py-16 text-center">
              <Loader2 className="w-12 h-12 animate-spin text-emerald-600 mx-auto mb-4" />
              <h2 className="text-lg font-semibold text-gray-800 mb-2">Creating Your Preview</h2>
              <p className="text-sm text-gray-500">{statusMessage}</p>
              <p className="text-xs text-gray-400 mt-2">This may take up to a minute…</p>
            </CardContent>
          </Card>
        )}

        {/* ── PREVIEW ── */}
        {step === STEPS.PREVIEW && previewImage && (
          <Card className="shadow-lg">
            <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-3">
              <CardTitle className="text-lg text-gray-800">Preview — Page 1</CardTitle>
              <CardDescription>
                Review the first page. If it looks good, generate the full {totalPages}-page storybook.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="rounded-lg overflow-hidden border border-gray-200 shadow-sm">
                <img src={previewImage} alt="Page 1 Preview" className="w-full" />
              </div>
              <div className="flex gap-3">
                <Button onClick={handleProceed}
                  className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white py-5 font-semibold">
                  <ChevronRight className="mr-1 h-4 w-4" />Proceed — Generate Full Book
                </Button>
                <Button onClick={handleCancel} variant="outline" className="py-5">
                  <X className="mr-1 h-4 w-4" />Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── GENERATING ── */}
        {step === STEPS.GENERATING && (
          <Card className="shadow-lg">
            <CardContent className="py-12 text-center space-y-5">
              <Loader2 className="w-12 h-12 animate-spin text-emerald-600 mx-auto" />
              <div>
                <h2 className="text-lg font-semibold text-gray-800 mb-1">Generating Your Storybook</h2>
                <p className="text-sm text-gray-500">{statusMessage}</p>
              </div>
              <p className="text-xs text-gray-400">
                Personalising {totalPages} pages with {childName || "your child"}'s face.
                Please keep this page open.
              </p>
            </CardContent>
          </Card>
        )}

        {/* ── COMPLETE ── */}
        {step === STEPS.COMPLETE && (
          <div className="space-y-4">
            {/* Success banner */}
            <Card className="shadow-lg border-emerald-200 bg-emerald-50">
              <CardContent className="py-6 text-center space-y-2">
                <div className="w-14 h-14 bg-emerald-100 rounded-full flex items-center justify-center mx-auto">
                  <CheckCircle className="w-8 h-8 text-emerald-600" />
                </div>
                <h2 className="text-xl font-bold text-emerald-800">
                  "{selectedStoryTitle}" is Ready!
                </h2>
                <p className="text-sm text-emerald-700">
                  Personalised for <strong>{childName}</strong> · {totalPages} pages
                </p>
              </CardContent>
            </Card>

            {/* How would you like it? */}
            <Card className="shadow-md">
              <CardHeader className="pb-3">
                <CardTitle className="text-lg text-gray-800">How would you like your storybook?</CardTitle>
                <CardDescription>Choose one or more — each is tracked separately in My Orders.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">

                {/* Option 1: Download PDF */}
                <button
                  onClick={() => navigate("/payment", {
                    state: {
                      orderType:    "pdf_download",
                      generationId,
                      childName:    childName.trim(),
                      storyId:      storyId || selectedStory,
                      storyTitle:   selectedStoryTitle,
                      totalPages,
                      pdfObjectUrl,
                    },
                  })}
                  className="w-full text-left rounded-xl border-2 border-indigo-200 bg-indigo-50
                    hover:border-indigo-400 hover:bg-indigo-100 transition-all p-4 group"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-xl bg-indigo-100 group-hover:bg-indigo-200
                      flex items-center justify-center flex-shrink-0 transition-colors">
                      <Download className="w-6 h-6 text-indigo-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-gray-800">Download PDF</p>
                      <p className="text-sm text-gray-500">Get the digital PDF file to keep forever</p>
                    </div>
                    <Badge className="bg-indigo-100 text-indigo-700 border-indigo-200 text-xs flex-shrink-0">
                      Free (Beta)
                    </Badge>
                  </div>
                </button>

                {/* Option 2: Email PDF */}
                <button
                  onClick={() => navigate("/payment", {
                    state: {
                      orderType:  "email_pdf",
                      generationId,
                      childName:  childName.trim(),
                      storyId:    storyId || selectedStory,
                      storyTitle: selectedStoryTitle,
                      totalPages,
                    },
                  })}
                  className="w-full text-left rounded-xl border-2 border-amber-200 bg-amber-50
                    hover:border-amber-400 hover:bg-amber-100 transition-all p-4 group"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-xl bg-amber-100 group-hover:bg-amber-200
                      flex items-center justify-center flex-shrink-0 transition-colors">
                      <Mail className="w-6 h-6 text-amber-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-gray-800">Email PDF</p>
                      <p className="text-sm text-gray-500">Send directly to your inbox</p>
                    </div>
                    <Badge className="bg-amber-100 text-amber-700 border-amber-200 text-xs flex-shrink-0">
                      Coming Soon
                    </Badge>
                  </div>
                </button>

                {/* Option 3: Printed Book */}
                <button
                  onClick={handleOrderPrint}
                  className="w-full text-left rounded-xl border-2 border-emerald-200 bg-emerald-50
                    hover:border-emerald-400 hover:bg-emerald-100 transition-all p-4 group"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-xl bg-emerald-100 group-hover:bg-emerald-200
                      flex items-center justify-center flex-shrink-0 transition-colors">
                      <Printer className="w-6 h-6 text-emerald-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-gray-800">Order Printed Book</p>
                      <p className="text-sm text-gray-500">Delivered to your door in 7–14 days</p>
                    </div>
                    <Badge className="bg-emerald-100 text-emerald-700 border-emerald-200 text-xs flex-shrink-0">
                      From ₹299
                    </Badge>
                  </div>
                </button>

              </CardContent>
            </Card>

            <Button onClick={resetAll} variant="ghost" size="sm"
              className="w-full text-gray-400 hover:text-gray-600">
              <RefreshCw className="mr-1 h-3 w-3" />Create Another Story
            </Button>
          </div>
        )}

        <div className="text-center mt-6 text-xs text-gray-400">
          <p>Powered by AI image generation · Each storybook is unique</p>
        </div>
      </div>
    </div>
  );
}
