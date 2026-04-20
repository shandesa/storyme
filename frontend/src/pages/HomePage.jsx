/**
 * HomePage.jsx — StoryMe main generation flow
 *
 * User flow:
 *   INPUT → PREVIEWING → PREVIEW → GENERATING → COMPLETE
 *
 * Why the "Proceed" button was broken (root cause):
 *   handleProceed() had `if (!sessionId) return` — but the preview endpoint
 *   never returned a session_id (stateless design). The button silently did
 *   nothing. Additionally, the proceed/status/download endpoints it called
 *   (/api/v2/generate/proceed, /status, /download) never existed in the backend.
 *
 * Fix:
 *   handleProceed() now calls POST /api/generate directly (the existing v1
 *   endpoint) with name + image + story_id. It receives a PDF blob in response
 *   and triggers an immediate browser download. No session or polling needed —
 *   the request waits for the full PDF (up to GENERATE_TIMEOUT_MS).
 */

import { useState, useEffect } from "react";
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
import { toast } from "sonner";
import {
  Loader2, Upload, BookOpen, Sparkles, ChevronRight,
  X, Download, RefreshCw, LogOut,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

// ─── API endpoints ─────────────────────────────────────────────────────────

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_V2      = `${BACKEND_URL}/api/v2`;   // preview + stories
const API_V1      = `${BACKEND_URL}/api`;       // full PDF generation

// Timeouts
const PREVIEW_TIMEOUT_MS  =  120_000;  // 2 min for page-1 preview
const GENERATE_TIMEOUT_MS =  600_000;  // 10 min for full storybook PDF

// ─── Steps ─────────────────────────────────────────────────────────────────

const STEPS = {
  INPUT:      "input",
  PREVIEWING: "previewing",
  PREVIEW:    "preview",
  GENERATING: "generating",
  COMPLETE:   "complete",
};

// ─── Component ─────────────────────────────────────────────────────────────

export default function HomePage() {
  const navigate = useNavigate();

  const [step, setStep]             = useState(STEPS.INPUT);
  const [childName, setChildName]   = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);   // local object URL for UI display
  const [stories, setStories]       = useState([]);
  const [selectedStory, setSelectedStory] = useState("forest_of_smiles");
  const [previewImage, setPreviewImage]   = useState(null);  // base64 preview from backend
  const [pdfBlob, setPdfBlob]       = useState(null);   // final PDF blob for download
  const [statusMessage, setStatusMessage] = useState("");
  const [totalPages, setTotalPages] = useState(0);

  // ── Fetch story list on mount ─────────────────────────────────────────────

  useEffect(() => {
    axios.get(`${API_V2}/stories`)
      .then((res) => setStories(res.data.stories || []))
      .catch(() => {});
  }, []);

  // ── File handling ─────────────────────────────────────────────────────────

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const allowed = ["image/jpeg", "image/jpg", "image/png", "image/webp"];
    if (!allowed.includes(file.type)) {
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

  // ── STEP 1 → STEP 2: Generate page-1 preview ─────────────────────────────

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

      const res = await axios.post(`${API_V2}/generate/preview`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: PREVIEW_TIMEOUT_MS,
      });

      // The story's total page count (for display in UI)
      const story = stories.find((s) => s.story_id === selectedStory);
      setTotalPages(story?.total_pages || 10);

      setPreviewImage(res.data.preview_image);
      setStep(STEPS.PREVIEW);
      toast.success("Preview ready — review page 1 and proceed.");
    } catch (err) {
      console.error("Preview failed:", err);
      toast.error(err.response?.data?.detail || "Preview generation failed");
      setStep(STEPS.INPUT);
    }
  };

  // ── STEP 2 → STEP 3: Generate full storybook PDF ─────────────────────────
  //
  // Calls POST /api/generate (v1) which:
  //   1. Composites every page with the child's face
  //   2. Generates a PDF
  //   3. Stores the PDF to Azure Blob at pdfs/{name}/{story}/{file}.pdf
  //   4. Returns the PDF as a file download response
  //
  // We receive it as a blob, store it in state, and trigger a browser download.
  // The COMPLETE step shows a re-download button in case the auto-download
  // was blocked by the browser.

  const handleProceed = async () => {
    if (!selectedFile || !childName.trim()) {
      toast.error("Missing photo or name — please start over.");
      setStep(STEPS.INPUT);
      return;
    }

    setStep(STEPS.GENERATING);
    setStatusMessage("Generating your personalised storybook…");

    try {
      const formData = new FormData();
      formData.append("name",     childName.trim());
      formData.append("image",    selectedFile);
      formData.append("story_id", selectedStory);

      // POST /api/generate — returns the full PDF as application/pdf
      const res = await axios.post(`${API_V1}/generate`, formData, {
        headers:      { "Content-Type": "multipart/form-data" },
        responseType: "blob",   // receive raw bytes for immediate download
        timeout:      GENERATE_TIMEOUT_MS,
        onUploadProgress: () => {
          setStatusMessage("Uploading photo…");
        },
      });

      const blob = new Blob([res.data], { type: "application/pdf" });
      setPdfBlob(blob);

      // Trigger automatic browser download
      _downloadBlob(blob, `${childName.replace(/\s+/g, "_")}_storybook.pdf`);

      setStep(STEPS.COMPLETE);
      setStatusMessage("Your storybook is ready!");
      toast.success("Storybook generated! Download started automatically.");
    } catch (err) {
      console.error("Full generation failed:", err);

      // Axios wraps blob error responses — try to parse the error message
      let detail = "Generation failed. Please try again.";
      if (err.response?.data instanceof Blob) {
        try {
          const text = await err.response.data.text();
          const json = JSON.parse(text);
          detail = json.detail || detail;
        } catch {
          /* ignore parse error */
        }
      } else if (err.response?.data?.detail) {
        detail = err.response.data.detail;
      } else if (err.code === "ECONNABORTED") {
        detail = "Generation timed out. The server may be busy — please try again.";
      }

      toast.error(detail);
      setStep(STEPS.PREVIEW);  // go back to preview so user can retry
    }
  };

  // ── Re-download from COMPLETE step ───────────────────────────────────────

  const handleDownload = () => {
    if (!pdfBlob) {
      toast.error("PDF not available — please generate again.");
      return;
    }
    _downloadBlob(pdfBlob, `${childName.replace(/\s+/g, "_")}_storybook.pdf`);
  };

  // ── Shared helper: trigger browser download from Blob ────────────────────

  const _downloadBlob = (blob, filename) => {
    const url  = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href     = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    setTimeout(() => {
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    }, 1000);
  };

  // ── Cancel / reset ────────────────────────────────────────────────────────

  const handleCancel = () => {
    setStep(STEPS.INPUT);
    setPreviewImage(null);
    setPdfBlob(null);
  };

  const resetAll = () => {
    setStep(STEPS.INPUT);
    setChildName("");
    setSelectedFile(null);
    setPreviewUrl(null);
    setPreviewImage(null);
    setPdfBlob(null);
    setTotalPages(0);
    setStatusMessage("");
  };

  const handleLogout = () => navigate("/");

  const selectedStoryTitle =
    stories.find((s) => s.story_id === selectedStory)
      ?.title?.replace("{name}", childName || "Your Child") ||
    "Forest of Smiles";

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-white to-emerald-50 py-8 px-4">
      <div className="max-w-2xl mx-auto">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <BookOpen className="w-9 h-9 text-emerald-600" />
            <h1 data-testid="app-title" className="text-4xl font-bold text-gray-900 tracking-tight">
              StoryMe
            </h1>
            <Sparkles className="w-7 h-7 text-amber-500" />
          </div>
          <Button variant="ghost" size="sm" onClick={handleLogout}
            className="text-gray-400 hover:text-gray-600">
            <LogOut className="w-4 h-4 mr-1" />
            Logout
          </Button>
        </div>

        <p className="text-base text-gray-500 text-center mb-6">
          AI-powered personalised storybooks for your child
        </p>

        {/* ── INPUT ── */}
        {step === STEPS.INPUT && (
          <Card className="shadow-lg border-emerald-100" data-testid="input-card">
            <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-4">
              <CardTitle className="text-xl text-gray-800">Create Your Story</CardTitle>
              <CardDescription>Upload a photo and choose a story to begin</CardDescription>
            </CardHeader>
            <CardContent className="pt-5">
              <form onSubmit={handlePreview} className="space-y-5">

                {/* Story selector */}
                <div className="space-y-1.5">
                  <Label className="text-gray-700 font-medium">Story</Label>
                  <Select value={selectedStory} onValueChange={setSelectedStory}
                    data-testid="story-select">
                    <SelectTrigger data-testid="story-select-trigger" className="border-gray-300">
                      <SelectValue placeholder="Select a story" />
                    </SelectTrigger>
                    <SelectContent>
                      {stories.map((s) => (
                        <SelectItem key={s.story_id} value={s.story_id}
                          data-testid={`story-option-${s.story_id}`}>
                          {s.title.replace("{name}", "Your Child")} ({s.total_pages} pages)
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Child's name */}
                <div className="space-y-1.5">
                  <Label htmlFor="childName" className="text-gray-700 font-medium">
                    Child's Name
                  </Label>
                  <Input
                    id="childName"
                    data-testid="child-name-input"
                    placeholder="Enter your child's name"
                    value={childName}
                    onChange={(e) => setChildName(e.target.value)}
                    className="border-gray-300"
                  />
                </div>

                {/* Photo upload */}
                <div className="space-y-1.5">
                  <Label className="text-gray-700 font-medium">Upload Photo</Label>
                  <div className="border-2 border-dashed border-gray-300 rounded-lg p-5 text-center hover:border-emerald-400 transition-colors">
                    {previewUrl ? (
                      <div className="space-y-3">
                        <img src={previewUrl} alt="Preview"
                          className="w-28 h-28 object-cover rounded-full mx-auto border-4 border-emerald-200"
                          data-testid="image-preview" />
                        <Button type="button" variant="outline" size="sm"
                          onClick={() => { setSelectedFile(null); setPreviewUrl(null); }}
                          data-testid="remove-image-btn">
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
                    <input id="photoUpload" data-testid="photo-upload-input" type="file"
                      accept="image/jpeg,image/jpg,image/png,image/webp"
                      onChange={handleFileChange} className="hidden" />
                  </div>
                </div>

                <Button type="submit" data-testid="generate-preview-btn"
                  className="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-5 text-base font-semibold">
                  <Sparkles className="mr-2 h-4 w-4" />
                  Generate Preview
                </Button>
              </form>
            </CardContent>
          </Card>
        )}

        {/* ── PREVIEWING ── */}
        {step === STEPS.PREVIEWING && (
          <Card className="shadow-lg" data-testid="previewing-card">
            <CardContent className="py-16 text-center">
              <Loader2 className="w-12 h-12 animate-spin text-emerald-600 mx-auto mb-4" />
              <h2 className="text-lg font-semibold text-gray-800 mb-2">
                Creating Your Preview
              </h2>
              <p className="text-sm text-gray-500">{statusMessage}</p>
              <p className="text-xs text-gray-400 mt-2">This may take up to a minute…</p>
            </CardContent>
          </Card>
        )}

        {/* ── PREVIEW ── */}
        {step === STEPS.PREVIEW && previewImage && (
          <Card className="shadow-lg" data-testid="preview-card">
            <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-3">
              <CardTitle className="text-lg text-gray-800">Preview — Page 1</CardTitle>
              <CardDescription>
                Review the first page. If you like it, proceed to generate the full{" "}
                {totalPages}-page storybook.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="rounded-lg overflow-hidden border border-gray-200 shadow-sm">
                <img src={previewImage} alt="Page 1 Preview" className="w-full"
                  data-testid="preview-image" />
              </div>
              <div className="flex gap-3">
                <Button onClick={handleProceed} data-testid="proceed-btn"
                  className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white py-5 font-semibold">
                  <ChevronRight className="mr-1 h-4 w-4" />
                  Proceed — Generate Full Book
                </Button>
                <Button onClick={handleCancel} variant="outline" data-testid="cancel-btn"
                  className="py-5">
                  <X className="mr-1 h-4 w-4" />
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── GENERATING ── */}
        {step === STEPS.GENERATING && (
          <Card className="shadow-lg" data-testid="generating-card">
            <CardContent className="py-12 text-center space-y-5">
              <Loader2 className="w-12 h-12 animate-spin text-emerald-600 mx-auto" />
              <div>
                <h2 className="text-lg font-semibold text-gray-800 mb-1">
                  Generating Your Storybook
                </h2>
                <p className="text-sm text-gray-500">{statusMessage}</p>
              </div>
              <p className="text-xs text-gray-400">
                Personalising {totalPages} pages with {childName || "your child"}'s face.
                This takes a few minutes — please keep this page open.
              </p>
            </CardContent>
          </Card>
        )}

        {/* ── COMPLETE ── */}
        {step === STEPS.COMPLETE && (
          <Card className="shadow-lg border-emerald-200" data-testid="complete-card">
            <CardContent className="py-10 text-center space-y-5">
              <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto">
                <BookOpen className="w-8 h-8 text-emerald-600" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-800 mb-1">
                  Your Storybook is Ready!
                </h2>
                <p className="text-sm text-gray-500">
                  "{selectedStoryTitle}" — {totalPages} pages
                </p>
                <p className="text-xs text-gray-400 mt-1">
                  Your download should have started automatically. If not, tap below.
                </p>
              </div>
              <div className="flex gap-3 justify-center">
                <Button onClick={handleDownload} data-testid="download-pdf-btn"
                  className="bg-emerald-600 hover:bg-emerald-700 text-white px-8 py-5 font-semibold">
                  <Download className="mr-2 h-4 w-4" />
                  Download PDF
                </Button>
                <Button onClick={resetAll} variant="outline" data-testid="create-another-btn"
                  className="py-5">
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Create Another
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Footer */}
        <div className="text-center mt-6 text-xs text-gray-400">
          <p>Powered by AI image generation &bull; Each storybook is unique</p>
        </div>

      </div>
    </div>
  );
}
