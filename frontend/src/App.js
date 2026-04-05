import { useState, useEffect, useRef, useCallback } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { toast } from "sonner";
import { Loader2, Upload, BookOpen, Sparkles, ChevronRight, X, Download, RefreshCw } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api/v2`;

const STEPS = {
  INPUT: "input",
  PREVIEWING: "previewing",
  PREVIEW: "preview",
  GENERATING: "generating",
  COMPLETE: "complete",
};

const Home = () => {
  const [step, setStep] = useState(STEPS.INPUT);
  const [childName, setChildName] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [stories, setStories] = useState([]);
  const [selectedStory, setSelectedStory] = useState("forest_of_smiles");
  const [sessionId, setSessionId] = useState(null);
  const [previewImage, setPreviewImage] = useState(null);
  const [progress, setProgress] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [statusMessage, setStatusMessage] = useState("");
  const pollRef = useRef(null);

  useEffect(() => {
    axios.get(`${API}/stories`).then(res => {
      setStories(res.data.stories || []);
    }).catch(() => {});
  }, []);

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

  const handlePreview = async (e) => {
    e.preventDefault();
    if (!childName.trim()) { toast.error("Please enter your child's name"); return; }
    if (!selectedFile) { toast.error("Please upload a photo"); return; }

    setStep(STEPS.PREVIEWING);
    setStatusMessage("Generating preview of page 1...");

    try {
      const formData = new FormData();
      formData.append("name", childName.trim());
      formData.append("image", selectedFile);
      formData.append("story_id", selectedStory);

      const res = await axios.post(`${API}/generate/preview`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      });

      setSessionId(res.data.session_id);
      setPreviewImage(res.data.preview_image);
      setStep(STEPS.PREVIEW);
      toast.success("Preview ready! Review and decide.");
    } catch (err) {
      console.error("Preview failed:", err);
      toast.error(err.response?.data?.detail || "Preview generation failed");
      setStep(STEPS.INPUT);
    }
  };

  const pollStatus = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await axios.get(`${API}/generate/status/${sessionId}`);
      const d = res.data;
      setProgress(d.progress);
      setTotalPages(d.total_pages);

      if (d.status === "complete" && d.pdf_ready) {
        clearInterval(pollRef.current);
        setStep(STEPS.COMPLETE);
        setStatusMessage("Your storybook is ready!");
        toast.success("Storybook generated successfully!");
      } else if (d.status === "failed") {
        clearInterval(pollRef.current);
        setStep(STEPS.INPUT);
        toast.error(d.error || "Generation failed");
      } else {
        setStatusMessage(`Generating page ${d.progress} of ${d.total_pages}...`);
      }
    } catch {
      // ignore transient polling errors
    }
  }, [sessionId]);

  const handleProceed = async () => {
    if (!sessionId) return;
    setStep(STEPS.GENERATING);
    setStatusMessage("Starting full generation...");

    try {
      await axios.post(`${API}/generate/proceed/${sessionId}`);
      // Polling will be started by the useEffect watching step === GENERATING
    } catch (err) {
      toast.error("Failed to start generation");
      setStep(STEPS.PREVIEW);
    }
  };

  useEffect(() => {
    if (step === STEPS.GENERATING && sessionId) {
      // Delay first poll to let backend start
      const timer = setTimeout(() => {
        pollRef.current = setInterval(pollStatus, 4000);
      }, 3000);
      return () => {
        clearTimeout(timer);
        if (pollRef.current) clearInterval(pollRef.current);
      };
    }
  }, [step, sessionId, pollStatus]);

  const handleCancel = () => {
    setStep(STEPS.INPUT);
    setSessionId(null);
    setPreviewImage(null);
    setProgress(0);
  };

  const handleDownload = async () => {
    if (!sessionId) return;
    try {
      const res = await axios.get(`${API}/generate/download/${sessionId}`, {
        responseType: "blob",
      });
      const blob = new Blob([res.data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${childName.replace(/\s+/g, "_")}_storybook.pdf`;
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);
      }, 1000);
    } catch {
      toast.error("Download failed");
    }
  };

  const resetAll = () => {
    setStep(STEPS.INPUT);
    setChildName("");
    setSelectedFile(null);
    setPreviewUrl(null);
    setSessionId(null);
    setPreviewImage(null);
    setProgress(0);
    setTotalPages(0);
    setStatusMessage("");
  };

  const selectedStoryTitle = stories.find(s => s.story_id === selectedStory)?.title?.replace("{name}", childName || "Your Child") || "Forest of Smiles";

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-white to-emerald-50 py-8 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center gap-2 mb-3">
            <BookOpen className="w-9 h-9 text-emerald-600" />
            <h1 data-testid="app-title" className="text-4xl font-bold text-gray-900 tracking-tight">StoryMe</h1>
            <Sparkles className="w-7 h-7 text-amber-500" />
          </div>
          <p className="text-base text-gray-500">AI-powered personalized storybooks for your child</p>
        </div>

        {/* === STEP 1: INPUT === */}
        {step === STEPS.INPUT && (
          <Card className="shadow-lg border-emerald-100" data-testid="input-card">
            <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-4">
              <CardTitle className="text-xl text-gray-800">Create Your Story</CardTitle>
              <CardDescription>Upload a photo and choose a story to begin</CardDescription>
            </CardHeader>
            <CardContent className="pt-5">
              <form onSubmit={handlePreview} className="space-y-5">
                {/* Story Selector */}
                <div className="space-y-1.5">
                  <Label className="text-gray-700 font-medium">Story</Label>
                  <Select value={selectedStory} onValueChange={setSelectedStory} data-testid="story-select">
                    <SelectTrigger data-testid="story-select-trigger" className="border-gray-300">
                      <SelectValue placeholder="Select a story" />
                    </SelectTrigger>
                    <SelectContent>
                      {stories.map(s => (
                        <SelectItem key={s.story_id} value={s.story_id} data-testid={`story-option-${s.story_id}`}>
                          {s.title.replace("{name}", "Your Child")} ({s.total_pages} pages)
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Name */}
                <div className="space-y-1.5">
                  <Label htmlFor="childName" className="text-gray-700 font-medium">Child's Name</Label>
                  <Input
                    id="childName"
                    data-testid="child-name-input"
                    placeholder="Enter your child's name"
                    value={childName}
                    onChange={(e) => setChildName(e.target.value)}
                    className="border-gray-300"
                  />
                </div>

                {/* Photo Upload */}
                <div className="space-y-1.5">
                  <Label className="text-gray-700 font-medium">Upload Photo</Label>
                  <div className="border-2 border-dashed border-gray-300 rounded-lg p-5 text-center hover:border-emerald-400 transition-colors">
                    {previewUrl ? (
                      <div className="space-y-3">
                        <img src={previewUrl} alt="Preview" className="w-28 h-28 object-cover rounded-full mx-auto border-4 border-emerald-200" data-testid="image-preview" />
                        <Button type="button" variant="outline" size="sm" onClick={() => { setSelectedFile(null); setPreviewUrl(null); }} data-testid="remove-image-btn">
                          Remove Photo
                        </Button>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        <Upload className="w-10 h-10 text-gray-400 mx-auto" />
                        <Label htmlFor="photoUpload" className="cursor-pointer text-emerald-600 hover:text-emerald-700 font-medium">
                          Click to upload
                        </Label>
                        <p className="text-xs text-gray-500">PNG, JPG, WEBP &mdash; Max 5MB</p>
                      </div>
                    )}
                    <input id="photoUpload" data-testid="photo-upload-input" type="file" accept="image/jpeg,image/jpg,image/png,image/webp" onChange={handleFileChange} className="hidden" />
                  </div>
                </div>

                {/* Generate Preview */}
                <Button type="submit" data-testid="generate-preview-btn" className="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-5 text-base font-semibold">
                  <Sparkles className="mr-2 h-4 w-4" />
                  Generate Preview
                </Button>
              </form>
            </CardContent>
          </Card>
        )}

        {/* === STEP: PREVIEWING (loading) === */}
        {step === STEPS.PREVIEWING && (
          <Card className="shadow-lg" data-testid="previewing-card">
            <CardContent className="py-16 text-center">
              <Loader2 className="w-12 h-12 animate-spin text-emerald-600 mx-auto mb-4" />
              <h2 className="text-lg font-semibold text-gray-800 mb-2">Creating Your Preview</h2>
              <p className="text-sm text-gray-500">{statusMessage}</p>
              <p className="text-xs text-gray-400 mt-2">This may take up to a minute...</p>
            </CardContent>
          </Card>
        )}

        {/* === STEP: PREVIEW (approve/reject) === */}
        {step === STEPS.PREVIEW && previewImage && (
          <Card className="shadow-lg" data-testid="preview-card">
            <CardHeader className="bg-gradient-to-r from-emerald-50 to-amber-50 pb-3">
              <CardTitle className="text-lg text-gray-800">Preview — Page 1</CardTitle>
              <CardDescription>Review the first page. If you like it, proceed to generate the full {totalPages || 16}-page storybook.</CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="rounded-lg overflow-hidden border border-gray-200 shadow-sm">
                <img src={previewImage} alt="Page 1 Preview" className="w-full" data-testid="preview-image" />
              </div>
              <div className="flex gap-3">
                <Button onClick={handleProceed} data-testid="proceed-btn" className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white py-5 font-semibold">
                  <ChevronRight className="mr-1 h-4 w-4" />
                  Proceed — Generate Full Book
                </Button>
                <Button onClick={handleCancel} variant="outline" data-testid="cancel-btn" className="py-5">
                  <X className="mr-1 h-4 w-4" />
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* === STEP: GENERATING (progress) === */}
        {step === STEPS.GENERATING && (
          <Card className="shadow-lg" data-testid="generating-card">
            <CardContent className="py-12 text-center space-y-5">
              <Loader2 className="w-12 h-12 animate-spin text-emerald-600 mx-auto" />
              <div>
                <h2 className="text-lg font-semibold text-gray-800 mb-1">Generating Your Storybook</h2>
                <p className="text-sm text-gray-500">{statusMessage}</p>
              </div>
              <div className="max-w-md mx-auto">
                <Progress value={totalPages > 0 ? (progress / totalPages) * 100 : 0} className="h-2" data-testid="progress-bar" />
                <p className="text-xs text-gray-400 mt-1">{progress} / {totalPages} pages</p>
              </div>
              <p className="text-xs text-gray-400">Each page is AI-generated and personalized. This takes a few minutes.</p>
            </CardContent>
          </Card>
        )}

        {/* === STEP: COMPLETE === */}
        {step === STEPS.COMPLETE && (
          <Card className="shadow-lg border-emerald-200" data-testid="complete-card">
            <CardContent className="py-10 text-center space-y-5">
              <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto">
                <BookOpen className="w-8 h-8 text-emerald-600" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-800 mb-1">Your Storybook is Ready!</h2>
                <p className="text-sm text-gray-500">"{selectedStoryTitle}" — {totalPages} pages</p>
              </div>
              <div className="flex gap-3 justify-center">
                <Button onClick={handleDownload} data-testid="download-pdf-btn" className="bg-emerald-600 hover:bg-emerald-700 text-white px-8 py-5 font-semibold">
                  <Download className="mr-2 h-4 w-4" />
                  Download PDF
                </Button>
                <Button onClick={resetAll} variant="outline" data-testid="create-another-btn" className="py-5">
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
};

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Home />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
