/**
 * HomePage.jsx — StoryMe main generation flow (v2)
 *
 * Step machine:
 *   INPUT → PREVIEWING → PREVIEW → FORMAT_SELECT → (navigate to payment/print)
 *
 * KEY CHANGES from v1:
 *   1. PREVIEW shows "Continue to Options" (not "Generate Full Book").
 *   2. FORMAT_SELECT shows Download / Email / Print options immediately.
 *   3. Background async generation fires the moment FORMAT_SELECT loads.
 *   4. PaymentPage receives bgGenStatus so it polls when needed.
 *   5. Back from PrintOrderPage/PaymentPage restores FORMAT_SELECT via generationCache.
 *   6. Legacy GENERATING + COMPLETE steps kept for backward compat.
 */

import { useState, useEffect, useRef } from "react";
import { clearSession, stopInactivityTimer, stopTokenRefresh } from "@/lib/session";
import { setGenCache, getGenCache, clearGenCache, updateGenCache } from "@/lib/generationCache";
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
import { Badge }    from "@/components/ui/badge";
import { toast }    from "sonner";
import {
  Loader2, Upload, BookOpen, Sparkles, ChevronRight,
  X, Download, RefreshCw, Printer, CheckCircle,
  Mail, Zap, Clock, User, Plus, Settings, BookMarked, ArrowDownCircle,
  ArrowLeft,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import AppHeader from "@/components/AppHeader";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_V2      = `${BACKEND_URL}/api/v2`;

const PREVIEW_TIMEOUT_MS = 120_000;

const STEPS = {
  PROFILE_SELECT: "profile_select",  // NEW: choose a kid profile
  INPUT:         "input",
  PREVIEWING:    "previewing",
  PREVIEW:       "preview",
  FORMAT_SELECT: "format_select",
  GENERATING:    "generating",   // legacy
  COMPLETE:      "complete",     // legacy
};

const GENERATION_MODES = [
  { value: "opencv", label: "Classic Storybook",
    description: "Fast face personalisation using computer vision (recommended)" },
  { value: "ai",     label: "AI-Powered Storybook",
    description: "AI generates each scene — slower but highly creative" },
];

const GENDER_OPTIONS = [
  { value: "neutral", label: "Neutral" },
  { value: "male",    label: "Boy"     },
  { value: "female",  label: "Girl"    },
];

export default function HomePage() {
  const navigate = useNavigate();

  const [step, setStep]                     = useState(STEPS.PROFILE_SELECT);
  const [childName, setChildName]           = useState("");
  const [selectedFile, setSelectedFile]     = useState(null);
  const [previewUrl, setPreviewUrl]         = useState(null);
  const [stories, setStories]               = useState([]);
  const [selectedStory, setSelectedStory]   = useState("forest_of_smiles");
  const [generationMode, setGenerationMode] = useState("opencv");
  const [gender, setGender]                 = useState("neutral");
  const [previewImage, setPreviewImage]     = useState(null);
  const [pdfBlob, setPdfBlob]               = useState(null);
  const [pdfObjectUrl, setPdfObjectUrl]     = useState(null);
  const [statusMessage, setStatusMessage]   = useState("");
  const [totalPages, setTotalPages]         = useState(0);
  const [generationId, setGenerationId]     = useState(null);
  const [storyId, setStoryId]               = useState(null);
  const [bgGenStatus, setBgGenStatus]       = useState(null);

  // Profile state
  const [profiles,          setProfiles]          = useState([]);
  const [selectedProfile,   setSelectedProfile]   = useState(null);  // {profile_id, name, gender, ...}
  const [pendingBooks,      setPendingBooks]       = useState([]);
  const [resumeDismissed,   setResumeDismissed]    = useState(false);
  const [profilesLoading,   setProfilesLoading]   = useState(false);

  const pollRef = useRef(null);

  const selectedStoryTitle =
    stories.find((s) => s.story_id === selectedStory)
      ?.title?.replace("{name}", childName || "Your Child") || "Forest of Smiles";

  useEffect(() => {
    axios.get(`${API_V2}/stories`).then((r) => setStories(r.data.stories || [])).catch(() => {});
  }, []);

  // ── Load profiles and pending downloads on mount ───────────────────────────
  useEffect(() => {
    const token = sessionStorage.getItem("storyme_token");
    if (!token) return;
    const headers = { Authorization: `Bearer ${token}` };

    // Load profiles
    setProfilesLoading(true);
    axios.get(`${BACKEND_URL}/api/v2/kids`, { headers })
      .then(r => {
        setProfiles(r.data.profiles || []);
        setProfilesLoading(false);
      })
      .catch(() => setProfilesLoading(false));

    // Load pending downloads (resume banner)
    axios.get(`${BACKEND_URL}/api/v2/books/pending-downloads`, { headers })
      .then(r => setPendingBooks(r.data.books || []))
      .catch(() => {});
  }, []);

  // ── Restore from cache (Back from PrintOrderPage / PaymentPage) ──────────────
  useEffect(() => {
    const cached = getGenCache();
    if (!cached || step !== STEPS.INPUT) return;
    const restorable = [STEPS.FORMAT_SELECT, STEPS.COMPLETE, STEPS.PREVIEW];
    if (!restorable.includes(cached.step)) return;

    setGenerationId(cached.generationId  || null);
    setStoryId(     cached.storyId       || null);
    setChildName(   cached.childName     || "");
    setTotalPages(  cached.totalPages    || 0);
    if (cached.pdfBlobUrl)    setPdfObjectUrl(cached.pdfBlobUrl);
    if (cached.bgGenStatus)   setBgGenStatus(cached.bgGenStatus);
    if (cached.generationMode) setGenerationMode(cached.generationMode);
    if (cached.gender)        setGender(cached.gender);
    if (cached.storyId)       setSelectedStory(cached.storyId);
    setStep(cached.step);

    if (cached.bgGenStatus === "generating" && cached.generationId) {
      _startPolling(cached.generationId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { return () => { if (pollRef.current) clearInterval(pollRef.current); }; }, []);

  // ── File handling ─────────────────────────────────────────────────────────────
  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!["image/jpeg","image/jpg","image/png","image/webp"].includes(file.type)) {
      toast.error("Please upload a valid image (JPG, PNG, or WEBP)"); return;
    }
    if (file.size > 5 * 1024 * 1024) { toast.error("File size must be less than 5MB"); return; }
    setSelectedFile(file);
    const reader = new FileReader();
    reader.onloadend = () => setPreviewUrl(reader.result);
    reader.readAsDataURL(file);
  };

  // ── Preview ───────────────────────────────────────────────────────────────────
  const handlePreview = async (e) => {
    e.preventDefault();

    // ── Profile-based flow: skip preview, go straight to async generation ─────
    // The preview API requires a raw image upload; profiles use a stored photo.
    // Rather than adding preview support to the backend profile endpoint, we
    // skip the preview step and begin background generation immediately.
    if (selectedProfile) {
      if (!selectedProfile.profile_id) {
        toast.error("Profile data is missing. Please go back and select a profile again.");
        return;
      }
      // Jump directly to FORMAT_SELECT and start async generation
      await handleContinueFromProfile();
      return;
    }

    // ── Ad-hoc upload flow: standard preview ─────────────────────────────────
    if (!childName.trim()) { toast.error("Please enter your child's name"); return; }
    if (!selectedFile)     { toast.error("Please upload a photo"); return; }
    setStep(STEPS.PREVIEWING);
    setStatusMessage("Generating preview of page 1…");
    try {
      const fd = new FormData();
      fd.append("name", childName.trim()); fd.append("image", selectedFile);
      fd.append("story_id", selectedStory); fd.append("mode", generationMode);
      fd.append("gender", gender);
      const res = await axios.post(`${API_V2}/generate/preview`, fd, {
        headers: { "Content-Type": "multipart/form-data" }, timeout: PREVIEW_TIMEOUT_MS,
      });
      const story = stories.find((s) => s.story_id === selectedStory);
      setTotalPages(story?.total_pages || 10);
      setStoryId(selectedStory);
      setPreviewImage(res.data.preview_image);
      setStep(STEPS.PREVIEW);
      toast.success("Preview ready — review page 1 and choose your format.");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Preview generation failed");
      setStep(STEPS.INPUT);
    }
  };

  // ── Profile-based: skip preview, start background generation directly ────────
  const handleContinueFromProfile = async () => {
    setStep(STEPS.FORMAT_SELECT);
    setBgGenStatus("generating");
    const story = stories.find((s) => s.story_id === selectedStory);
    setTotalPages(story?.total_pages || 10);
    setStoryId(selectedStory);
    try {
      // Auth header is required so the backend can resolve user_mobile and
      // look up the kid profile's stored photo by profile_id.
      // Without it, get_mobile_from_request() returns None and the backend
      // returns HTTP 400 ("Either profile_id or image is required").
      const token = sessionStorage.getItem("storyme_token");
      if (!token) {
        toast.error("Your session has expired. Please log in again.");
        setBgGenStatus("failed");
        return;
      }

      const fd = new FormData();
      fd.append("name",       selectedProfile.name);
      fd.append("story_id",   selectedStory);
      fd.append("mode",       generationMode);
      fd.append("gender",     selectedProfile.gender);
      fd.append("profile_id", selectedProfile.profile_id);
      const res = await axios.post(`${API_V2}/generate/async`, fd, {
        headers: {
          "Content-Type":  "multipart/form-data",
          "Authorization": `Bearer ${token}`,
        },
        timeout: 30_000,
      });
      const newGenId = res.data.generation_id;
      setGenerationId(newGenId);
      _startPolling(newGenId);
      toast.success("Your storybook is generating — choose your format below.");
    } catch (err) {
      const detail = err.response?.data?.detail || "";
      if (err.response?.status === 401) {
        toast.error("Your session has expired. Please log in again.");
      } else if (err.response?.status === 404) {
        toast.error("Profile not found. Please go back and select a profile again.");
      } else {
        toast.error(detail || "Generation start failed. Please try again.");
      }
      setBgGenStatus("failed");
    }
  };

  // ── Continue to format select (ad-hoc upload path, called after PREVIEW) ────
  const handleContinueToOptions = async () => {
    if (!selectedFile && !selectedProfile) {
      toast.error("Please select a profile or upload a photo."); setStep(STEPS.INPUT); return;
    }
    if (!selectedProfile && !childName.trim()) {
      toast.error("Missing name — please start over."); setStep(STEPS.INPUT); return;
    }

    // Profile path is handled by handleContinueFromProfile (called from handlePreview)
    // This function handles only the ad-hoc upload path
    setStep(STEPS.FORMAT_SELECT);
    setBgGenStatus("generating");
    try {
      const fd = new FormData();
      fd.append("name",     childName.trim());
      fd.append("story_id", selectedStory);
      fd.append("mode",     generationMode);
      fd.append("gender",   gender);
      fd.append("image",    selectedFile);
      const res = await axios.post(`${API_V2}/generate/async`, fd, {
        headers: { "Content-Type": "multipart/form-data" }, timeout: 30_000,
      });
      const newGenId = res.data.generation_id;
      setGenerationId(newGenId);
      _startPolling(newGenId);
      toast.success("Storybook generating in the background — choose your format below.");
    } catch {
      toast.error("Generation start failed. Please try again.");
      setBgGenStatus("failed");
    }
  };

  // ── Polling ───────────────────────────────────────────────────────────────────
  const _startPolling = (genId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const res = await axios.get(`${API_V2}/generate/status/${genId}`, { timeout: 10_000 });
        const st = res.data.status;
        setBgGenStatus(st);
        updateGenCache({ bgGenStatus: st });
        if (st === "complete" || st === "failed") {
          clearInterval(pollRef.current); pollRef.current = null;
          if (st === "complete") toast.success("Your storybook is ready! Proceed to checkout.");
        }
      } catch { /* keep polling on blip */ }
    }, 4000);
  };

  // ── Navigate with cache write ─────────────────────────────────────────────────
  const _writeCache = () => setGenCache({
    step: STEPS.FORMAT_SELECT, generationId, childName: childName.trim(),
    storyId: storyId || selectedStory, storyTitle: selectedStoryTitle,
    totalPages, bgGenStatus, pdfBlobUrl: pdfObjectUrl || null,
    generationMode, gender,
  });

  const handleSelectDigital = (orderType) => {
    _writeCache();
    navigate("/payment", {
      state: {
        orderType, generationId, childName: childName.trim(),
        storyId: storyId || selectedStory, storyTitle: selectedStoryTitle,
        totalPages, bgGenStatus, pdfObjectUrl: pdfObjectUrl || null,
      },
    });
  };

  const handleOrderPrint = () => {
    _writeCache();
    navigate("/print-order", {
      state: {
        generationId, childName: childName.trim(),
        storyId: storyId || selectedStory, bgGenStatus, totalPages,
        storyTitle: selectedStoryTitle,
      },
    });
  };

  const handleCancel = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    setStep(STEPS.INPUT); setPreviewImage(null); setPdfBlob(null); setBgGenStatus(null);
  };

  const resetAll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    clearGenCache();
    if (pdfObjectUrl) window.URL.revokeObjectURL(pdfObjectUrl);
    setSelectedProfile(null);
    setStep(STEPS.PROFILE_SELECT); setChildName(""); setSelectedFile(null);
    setPreviewUrl(null); setPreviewImage(null); setPdfBlob(null);
    setPdfObjectUrl(null); setTotalPages(0); setStatusMessage("");
    setGenerationId(null); setStoryId(null); setBgGenStatus(null);
  };

  const handleLogout = () => {
    clearGenCache(); clearSession(); stopInactivityTimer(); stopTokenRefresh();
    navigate("/", { replace: true });
  };

  // ── Progress banner (shown in FORMAT_SELECT while generating) ────────────────
  const GenBanner = () => {
    if (!bgGenStatus || bgGenStatus === "complete") return null;
    if (bgGenStatus === "failed") return (
      <div className="flex items-center gap-3 rounded-xl bg-red-50 border border-red-200 px-4 py-3">
        <X className="w-4 h-4 text-red-500 shrink-0" />
        <span className="text-sm text-red-700">Generation failed — please go back and try again.</span>
      </div>
    );
    return (
      <div className="flex items-center gap-3 rounded-xl bg-amber-50 border border-amber-200 px-4 py-3">
        <Loader2 className="w-4 h-4 text-amber-500 animate-spin shrink-0" />
        <div className="flex-1">
          <p className="text-sm text-amber-800 font-medium">Storybook generating in background…</p>
          <p className="text-xs text-amber-600 mt-0.5">
            Choose your format now. We'll confirm it's ready before you pay.
          </p>
        </div>
        <Clock className="w-4 h-4 text-amber-400 shrink-0" />
      </div>
    );
  };

  const genReady = bgGenStatus === "complete";

  // ── Option cards (shared between FORMAT_SELECT and legacy COMPLETE) ───────────
  const OptionCards = () => (
    <div className="space-y-3">
      <button onClick={() => handleSelectDigital("pdf_download")}
        className="w-full text-left rounded-xl border-2 border-indigo-200 bg-indigo-50 hover:border-indigo-400 hover:bg-indigo-100 transition-all p-4 group">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-indigo-100 group-hover:bg-indigo-200 flex items-center justify-center flex-shrink-0 transition-colors">
            <Download className="w-6 h-6 text-indigo-600" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-gray-800">Download PDF</p>
            <p className="text-sm text-gray-500">Get the digital PDF file to keep forever</p>
          </div>
          <Badge className="bg-indigo-100 text-indigo-700 border-indigo-200 text-xs flex-shrink-0">₹199</Badge>
        </div>
      </button>

      <button onClick={() => handleSelectDigital("email_pdf")}
        className="w-full text-left rounded-xl border-2 border-amber-200 bg-amber-50 hover:border-amber-400 hover:bg-amber-100 transition-all p-4 group">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-amber-100 group-hover:bg-amber-200 flex items-center justify-center flex-shrink-0 transition-colors">
            <Mail className="w-6 h-6 text-amber-600" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-gray-800">Email PDF</p>
            <p className="text-sm text-gray-500">Send directly to your inbox</p>
          </div>
          <Badge className="bg-amber-100 text-amber-700 border-amber-200 text-xs flex-shrink-0">₹199</Badge>
        </div>
      </button>

      <button onClick={handleOrderPrint}
        className="w-full text-left rounded-xl border-2 border-emerald-200 bg-emerald-50 hover:border-emerald-400 hover:bg-emerald-100 transition-all p-4 group">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-emerald-100 group-hover:bg-emerald-200 flex items-center justify-center flex-shrink-0 transition-colors">
            <Printer className="w-6 h-6 text-emerald-600" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-gray-800">Order Printed Book</p>
            <p className="text-sm text-gray-500">Delivered to your door in 7–14 days</p>
          </div>
          <Badge className="bg-emerald-100 text-emerald-700 border-emerald-200 text-xs flex-shrink-0">From ₹299</Badge>
        </div>
      </button>
    </div>
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-white to-emerald-50 py-8 px-4">
      <div className="max-w-2xl mx-auto">
        <AppHeader />
        <p className="text-base text-gray-500 text-center mb-6">AI-powered personalised storybooks for your child</p>


        {/* PROFILE_SELECT — choose existing profile or start with new photo */}
        {step === STEPS.PROFILE_SELECT && (
          <div className="space-y-4">

            {/* Resume Banner — undownloaded completed book */}
            {!resumeDismissed && pendingBooks.length > 0 && (() => {
              const book = pendingBooks[0];
              const handleResume = async () => {
                const token = sessionStorage.getItem("storyme_token");
                if (!token) return;
                const link = document.createElement("a");
                link.href = `${BACKEND_URL}${book.download_url}`;
                link.download = "";
                document.body.appendChild(link);
                link.click();
                setTimeout(() => document.body.removeChild(link), 1000);
                // Acknowledge download
                axios.post(
                  `${BACKEND_URL}/api/v2/books/${book.book_id}/downloaded`,
                  {},
                  { headers: { Authorization: `Bearer ${token}` } }
                ).catch(() => {});
                setPendingBooks([]);
              };
              return (
                <Card className="border-2 border-emerald-300 bg-emerald-50 shadow-md">
                  <CardContent className="py-4 px-4">
                    <div className="flex items-start gap-3">
                      <BookMarked className="w-5 h-5 text-emerald-600 flex-shrink-0 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-emerald-800">
                          Your storybook is ready to download!
                        </p>
                        <p className="text-xs text-emerald-700 mt-0.5 truncate">
                          "{book.story_title}" for {book.child_name || book.profile_name}
                        </p>
                      </div>
                      <button onClick={() => setResumeDismissed(true)}
                        className="text-emerald-500 hover:text-emerald-700 flex-shrink-0">
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                    <div className="flex gap-2 mt-3">
                      <Button onClick={handleResume} size="sm"
                        className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white text-xs">
                        <ArrowDownCircle className="w-3.5 h-3.5 mr-1" />Download Now
                      </Button>
                      <Button onClick={() => setResumeDismissed(true)} size="sm"
                        variant="outline" className="text-xs text-gray-500">
                        Dismiss
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              );
            })()}

            {/* Profiles header */}
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-gray-800">Whose story?</h2>
                <p className="text-xs text-gray-500">Select a profile or create a new one</p>
              </div>
              <button onClick={() => navigate("/profiles")}
                className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1">
                <Settings className="w-3 h-3" />Manage
              </button>
            </div>

            {/* Profile grid */}
            {profilesLoading ? (
              <div className="flex items-center justify-center h-24 text-gray-400">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading profiles…
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                {profiles.map(p => (
                  <button
                    key={p.profile_id}
                    onClick={() => {
                      setSelectedProfile(p);
                      setChildName(p.name);
                      setGender(p.gender);
                      setStep(STEPS.INPUT);
                    }}
                    className="flex flex-col items-center gap-2 rounded-xl border-2 border-gray-200 hover:border-emerald-400 hover:bg-emerald-50 transition-all p-4 text-center"
                  >
                    <div className="w-14 h-14 rounded-full bg-emerald-100 flex items-center justify-center overflow-hidden border-2 border-emerald-200">
                      {p.has_photo ? (
                        <img
                          src={`${BACKEND_URL}/api/v2/kids/${p.profile_id}/photo`}
                          alt={p.name}
                          className="w-full h-full object-cover"
                          onError={e => { e.target.style.display="none"; }}
                        />
                      ) : (
                        <span className="text-xl font-bold text-emerald-700">
                          {p.name?.[0]?.toUpperCase()}
                        </span>
                      )}
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-gray-800">{p.name}</p>
                      {p.age > 0 && (
                        <p className="text-xs text-gray-400">{p.age} yrs</p>
                      )}
                    </div>
                  </button>
                ))}

                {/* Create new profile shortcut */}
                <button
                  onClick={() => navigate("/profiles")}
                  className="flex flex-col items-center gap-2 rounded-xl border-2 border-dashed border-gray-300 hover:border-emerald-400 hover:bg-emerald-50 transition-all p-4 text-center text-gray-400 hover:text-emerald-600"
                >
                  <div className="w-14 h-14 rounded-full border-2 border-dashed border-gray-300 flex items-center justify-center">
                    <Plus className="w-6 h-6" />
                  </div>
                  <p className="text-sm font-medium">New Profile</p>
                </button>
              </div>
            )}

            {/* Skip — use new photo without a profile */}
            <button
              onClick={() => { setSelectedProfile(null); setStep(STEPS.INPUT); }}
              className="w-full text-xs text-gray-400 hover:text-gray-600 py-2 text-center"
            >
              Skip — use a one-time photo without saving a profile
            </button>
          </div>
        )}

        {/* INPUT */}
        {step === STEPS.INPUT && (
          <Card className="shadow-lg border-emerald-100">
            <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-4">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-xl text-gray-800">
                    {selectedProfile ? `${selectedProfile.name}'s Story` : "Create Your Story"}
                  </CardTitle>
                  <CardDescription>
                    {selectedProfile ? "Choose a story to generate" : "Upload a photo and choose a story to begin"}
                  </CardDescription>
                </div>
                <button onClick={() => { setSelectedProfile(null); setStep(STEPS.PROFILE_SELECT); }}
                  className="text-xs text-gray-400 hover:text-gray-600">
                  <ArrowLeft className="w-4 h-4" />
                </button>
              </div>
            </CardHeader>
            <CardContent className="pt-5">
              <div className="space-y-5">
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
                          <span className="font-medium">{m.label}</span>
                          <span className="text-xs text-gray-500 ml-2">{m.description}</span>
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
                      {GENDER_OPTIONS.map((g) => (<SelectItem key={g.value} value={g.value}>{g.label}</SelectItem>))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="childName" className="text-gray-700 font-medium">Child's Name</Label>
                  <Input id="childName" placeholder="Enter your child's name" value={childName}
                    onChange={(e) => !selectedProfile && setChildName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handlePreview(e)}
                    className={`border-gray-300 ${selectedProfile ? "bg-gray-50 text-gray-500" : ""}`}
                    readOnly={!!selectedProfile} />
                </div>
                {!selectedProfile && (
                  <div className="space-y-1.5">
                    <Label className="text-gray-700 font-medium">Upload Photo</Label>
                    <div className="border-2 border-dashed border-gray-300 rounded-lg p-5 text-center hover:border-emerald-400 transition-colors">
                      {previewUrl ? (
                        <div className="space-y-3">
                          <img src={previewUrl} alt="Preview" className="w-28 h-28 object-cover rounded-full mx-auto border-4 border-emerald-200" />
                          <Button type="button" variant="outline" size="sm"
                            onClick={() => { setSelectedFile(null); setPreviewUrl(null); }}>Remove Photo</Button>
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <Upload className="w-10 h-10 text-gray-400 mx-auto" />
                          <Label htmlFor="photoUpload" className="cursor-pointer text-emerald-600 hover:text-emerald-700 font-medium">Click to upload</Label>
                          <p className="text-xs text-gray-500">PNG, JPG, WEBP — Max 5MB</p>
                        </div>
                      )}
                      <input id="photoUpload" type="file" accept="image/jpeg,image/jpg,image/png,image/webp"
                        onChange={handleFileChange} className="hidden" />
                    </div>
                  </div>
                )}
                {selectedProfile && selectedProfile.has_photo && (
                  <div className="flex items-center gap-3 rounded-lg bg-emerald-50 border border-emerald-200 p-3">
                    <div className="w-12 h-12 rounded-full overflow-hidden border-2 border-emerald-300 flex-shrink-0">
                      <img
                        src={`${BACKEND_URL}/api/v2/kids/${selectedProfile.profile_id}/photo`}
                        alt={selectedProfile.name}
                        className="w-full h-full object-cover"
                      />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-emerald-800">Using {selectedProfile.name}'s saved photo</p>
                      <p className="text-xs text-emerald-600">No re-upload needed</p>
                    </div>
                  </div>
                )}
                <Button onClick={handlePreview} className="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-5 text-base font-semibold">
                  <Sparkles className="mr-2 h-4 w-4" />
                  {selectedProfile ? "Generate Story" : "Generate Preview"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* PREVIEWING */}
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

        {/* PREVIEW */}
        {step === STEPS.PREVIEW && previewImage && (
          <Card className="shadow-lg">
            <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-3">
              <CardTitle className="text-lg text-gray-800">Preview — Page 1</CardTitle>
              <CardDescription>
                Happy with this? Continue to choose your format.
                The full {totalPages}-page storybook generates in the background while you decide.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="rounded-lg overflow-hidden border border-gray-200 shadow-sm">
                <img src={previewImage} alt="Page 1 Preview" className="w-full" />
              </div>
              <div className="flex gap-3">
                <Button onClick={handleContinueToOptions}
                  className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white py-5 font-semibold">
                  <ChevronRight className="mr-1 h-4 w-4" />Continue to Options
                </Button>
                <Button onClick={handleCancel} variant="outline" className="py-5">
                  <X className="mr-1 h-4 w-4" />Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* FORMAT_SELECT — primary new step */}
        {step === STEPS.FORMAT_SELECT && (
          <div className="space-y-4">
            <Card className={`shadow-lg border-2 ${genReady ? "border-emerald-200 bg-emerald-50" : "border-amber-100 bg-amber-50"}`}>
              <CardContent className="py-5 text-center space-y-1">
                <div className={`w-12 h-12 ${genReady ? "bg-emerald-100" : "bg-amber-100"} rounded-full flex items-center justify-center mx-auto mb-2`}>
                  {genReady
                    ? <CheckCircle className="w-7 h-7 text-emerald-600" />
                    : <Zap className="w-7 h-7 text-amber-500" />}
                </div>
                <h2 className={`text-xl font-bold ${genReady ? "text-emerald-800" : "text-amber-800"}`}>
                  {genReady ? `"${selectedStoryTitle}" is Ready!` : "Preview Approved!"}
                </h2>
                <p className={`text-sm ${genReady ? "text-emerald-700" : "text-amber-700"}`}>
                  Personalised for <strong>{childName}</strong> · {totalPages} pages
                </p>
              </CardContent>
            </Card>

            <GenBanner />

            <Card className="shadow-md">
              <CardHeader className="pb-3">
                <CardTitle className="text-lg text-gray-800">How would you like your storybook?</CardTitle>
                <CardDescription>
                  {genReady
                    ? "Your storybook is ready — choose a format below."
                    : "Select a format now. We'll confirm it's ready before you pay."}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <OptionCards />
              </CardContent>
            </Card>

            <Button onClick={resetAll} variant="ghost" size="sm" className="w-full text-gray-400 hover:text-gray-600">
              <RefreshCw className="mr-1 h-3 w-3" />Create Another Story
            </Button>
          </div>
        )}

        {/* LEGACY: GENERATING */}
        {step === STEPS.GENERATING && (
          <Card className="shadow-lg">
            <CardContent className="py-12 text-center space-y-5">
              <Loader2 className="w-12 h-12 animate-spin text-emerald-600 mx-auto" />
              <div>
                <h2 className="text-lg font-semibold text-gray-800 mb-1">Generating Your Storybook</h2>
                <p className="text-sm text-gray-500">{statusMessage}</p>
              </div>
              <p className="text-xs text-gray-400">Personalising {totalPages} pages. Please keep this page open.</p>
            </CardContent>
          </Card>
        )}

        {/* LEGACY: COMPLETE */}
        {step === STEPS.COMPLETE && (
          <div className="space-y-4">
            <Card className="shadow-lg border-emerald-200 bg-emerald-50">
              <CardContent className="py-6 text-center space-y-2">
                <div className="w-14 h-14 bg-emerald-100 rounded-full flex items-center justify-center mx-auto">
                  <CheckCircle className="w-8 h-8 text-emerald-600" />
                </div>
                <h2 className="text-xl font-bold text-emerald-800">"{selectedStoryTitle}" is Ready!</h2>
                <p className="text-sm text-emerald-700">Personalised for <strong>{childName}</strong> · {totalPages} pages</p>
              </CardContent>
            </Card>
            <Card className="shadow-md">
              <CardHeader className="pb-3">
                <CardTitle className="text-lg text-gray-800">How would you like your storybook?</CardTitle>
              </CardHeader>
              <CardContent><OptionCards /></CardContent>
            </Card>
            <Button onClick={resetAll} variant="ghost" size="sm" className="w-full text-gray-400 hover:text-gray-600">
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
