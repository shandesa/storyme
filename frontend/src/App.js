import { useState } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { Loader2, Upload, BookOpen, Sparkles } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const Home = () => {
  const [childName, setChildName] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedPdfUrl, setGeneratedPdfUrl] = useState(null);
  const [pdfFilename, setPdfFilename] = useState("");


  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      // Validate file type
      const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
      if (!allowedTypes.includes(file.type)) {
        toast.error("Please upload a valid image file (JPG, PNG, or WEBP)");
        return;
      }

      // Validate file size (max 5MB)
      if (file.size > 5 * 1024 * 1024) {
        toast.error("File size must be less than 5MB");
        return;
      }

      setSelectedFile(file);
      
      // Create preview
      const reader = new FileReader();
      reader.onloadend = () => {
        setPreviewUrl(reader.result);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    // Validation
    if (!childName.trim()) {
      toast.error("Please enter your child's name");
      return;
    }

    if (!selectedFile) {
      toast.error("Please upload a photo");
      return;
    }

    setIsGenerating(true);

    try {
      console.log("=== PDF Generation Started ===");
      console.log("Child name:", childName);
      console.log("File:", selectedFile?.name, selectedFile?.type, selectedFile?.size);
      
      const formData = new FormData();
      formData.append('name', childName.trim());
      formData.append('image', selectedFile);

      console.log("Sending request to:", `${API}/generate`);
      
      const response = await axios.post(`${API}/generate`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        responseType: 'blob', // Important for file download
      });

      console.log("=== Response Received ===");
      console.log("Status:", response.status);
      console.log("Content-Type:", response.headers['content-type']);
      console.log("Content-Disposition:", response.headers['content-disposition']);
      console.log("Data type:", typeof response.data);
      console.log("Data size:", response.data.size, "bytes");
      console.log("Data is Blob:", response.data instanceof Blob);

      // Verify we have a valid PDF blob
      if (!response.data || response.data.size === 0) {
        throw new Error("Received empty PDF data");
      }

      if (response.data.type !== 'application/pdf') {
        console.warn("Warning: Content-Type is not application/pdf, got:", response.data.type);
      }

      console.log("=== Creating Download ===");
      
      // Create blob URL
      const blob = new Blob([response.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const filename = `${childName.replace(/\s+/g, '_')}_storybook.pdf`;
      
      console.log("Blob URL created:", url);
      console.log("Filename:", filename);

      // Store PDF URL for manual download button (in case auto-download fails)
      setGeneratedPdfUrl(url);
      setPdfFilename(filename);

      // Method 1: Standard download link (try first)
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.style.display = 'none';
      
      document.body.appendChild(link);
      console.log("Link appended to DOM");
      
      // Trigger click
      link.click();
      console.log("Link clicked");
      
      // Keep link for a bit (don't remove immediately)
      setTimeout(() => {
        if (document.body.contains(link)) {
          document.body.removeChild(link);
        }
        console.log("Link cleanup attempted");
      }, 1000);

      toast.success("Storybook created! If download doesn't start, click the Download button below.");
      console.log("=== Download Complete ===");

      // Don't reset form immediately - let user download first
      // Reset will happen when they start a new generation
      
      
    } catch (error) {
      console.error("=== Error generating storybook ===");
      console.error("Error type:", error.name);
      console.error("Error message:", error.message);
      console.error("Full error:", error);
      
      if (error.response) {
        console.error("Response status:", error.response.status);
        console.error("Response data:", error.response.data);
      }
      
      toast.error(error.response?.data?.detail || error.message || "Failed to generate storybook. Please try again.");
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-indigo-50 py-12 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-4">
            <BookOpen className="w-10 h-10 text-blue-600" />
            <h1 className="text-4xl font-bold text-gray-900">StoryMe</h1>
            <Sparkles className="w-8 h-8 text-yellow-500" />
          </div>
          <p className="text-lg text-gray-600">
            Create a personalized storybook for your child
          </p>
        </div>

        {/* Form Card */}
        <Card className="shadow-lg border-blue-100" data-testid="story-generation-card">
          <CardHeader className="bg-gradient-to-r from-blue-50 to-indigo-50">
            <CardTitle className="text-2xl text-gray-800">Create Your Story</CardTitle>
            <CardDescription className="text-gray-600">
              Upload your child's photo and enter their name to generate a magical storybook
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Child Name Input */}
              <div className="space-y-2">
                <Label htmlFor="childName" className="text-gray-700 font-medium">
                  Child's Name
                </Label>
                <Input
                  id="childName"
                  data-testid="child-name-input"
                  type="text"
                  placeholder="Enter your child's name"
                  value={childName}
                  onChange={(e) => setChildName(e.target.value)}
                  className="border-gray-300 focus:border-blue-500 focus:ring-blue-500"
                  disabled={isGenerating}
                />
              </div>

              {/* File Upload */}
              <div className="space-y-2">
                <Label htmlFor="photoUpload" className="text-gray-700 font-medium">
                  Upload Photo
                </Label>
                <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-blue-400 transition-colors">
                  {previewUrl ? (
                    <div className="space-y-4">
                      <img
                        src={previewUrl}
                        alt="Preview"
                        className="w-32 h-32 object-cover rounded-full mx-auto border-4 border-blue-200"
                        data-testid="image-preview"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setSelectedFile(null);
                          setPreviewUrl(null);
                        }}
                        disabled={isGenerating}
                        data-testid="remove-image-button"
                      >
                        Remove Photo
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <Upload className="w-12 h-12 text-gray-400 mx-auto" />
                      <div>
                        <Label
                          htmlFor="photoUpload"
                          className="cursor-pointer text-blue-600 hover:text-blue-700 font-medium"
                        >
                          Click to upload
                        </Label>
                        <p className="text-sm text-gray-500 mt-1">
                          or drag and drop (PNG, JPG, WEBP - Max 5MB)
                        </p>
                      </div>
                    </div>
                  )}
                  <input
                    id="photoUpload"
                    data-testid="photo-upload-input"
                    type="file"
                    accept="image/jpeg,image/jpg,image/png,image/webp"
                    onChange={handleFileChange}
                    className="hidden"
                    disabled={isGenerating}
                  />
                </div>
              </div>

              {/* Submit Button */}
              <Button
                type="submit"
                data-testid="generate-story-button"
                className="w-full bg-blue-600 hover:bg-blue-700 text-white py-6 text-lg font-semibold shadow-md hover:shadow-lg transition-all"
                disabled={isGenerating}
              >
                {isGenerating ? (
                  <>
                    <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                    Creating Your Story...
                  </>
                ) : (
                  <>
                    <BookOpen className="mr-2 h-5 w-5" />
                    Generate Storybook
                  </>
                )}
              </Button>
            </form>

            {/* Success Message with Manual Download Button */}
            {generatedPdfUrl && (
              <div className="mt-6 p-6 bg-green-50 rounded-lg border-2 border-green-200" data-testid="download-success">
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0">
                    <BookOpen className="w-6 h-6 text-green-600" />
                  </div>
                  <div className="flex-1">
                    <h3 className="font-semibold text-green-800 text-lg mb-2">
                      ✓ Storybook Created Successfully!
                    </h3>
                    <p className="text-sm text-green-700 mb-4">
                      Your personalized storybook is ready. If the download didn't start automatically, 
                      click the button below.
                    </p>
                    <div className="flex gap-3">
                      <Button
                        onClick={() => {
                          console.log("Manual download button clicked");
                          const link = document.createElement('a');
                          link.href = generatedPdfUrl;
                          link.download = pdfFilename;
                          link.click();
                        }}
                        className="bg-green-600 hover:bg-green-700"
                        data-testid="manual-download-button"
                      >
                        <BookOpen className="mr-2 h-4 w-4" />
                        Download PDF
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => {
                          // Reset for new story
                          setChildName("");
                          setSelectedFile(null);
                          setPreviewUrl(null);
                          setGeneratedPdfUrl(null);
                          setPdfFilename("");
                          window.URL.revokeObjectURL(generatedPdfUrl);
                        }}
                        data-testid="create-another-button"
                      >
                        Create Another Story
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Info */}
            <div className="mt-6 p-4 bg-blue-50 rounded-lg border border-blue-100">
              <p className="text-sm text-gray-700">
                <span className="font-semibold text-blue-700">Story:</span> The Forest of Smiles - 
                A magical 10-page adventure where your child meets friendly animals and learns 
                about kindness, peace, and joy.
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Footer */}
        <div className="text-center mt-8 text-sm text-gray-500">
          <p>Create beautiful, personalized storybooks in seconds</p>
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
