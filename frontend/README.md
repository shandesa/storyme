# Frontend - React Application

## Purpose

The `frontend/` directory contains the React-based user interface for StoryMe. It provides a clean, accessible form for uploading photos, entering child names, and generating personalized storybooks with real-time feedback and download capabilities.

## Placement in Architecture

```
       User Browser
            │
            ↓
┌─────────────────────────────┐
│   FRONTEND (React)         │  ← YOU ARE HERE
│  - Upload interface        │
│  - Form validation         │
│  - Download handling       │
└────────────┬────────────────┘
            │ REST API
            ↓
┌────────────┴────────────────┐
│   Backend (FastAPI)       │
└─────────────────────────────┘
```

## Structure

```
frontend/
├── public/
│   ├── index.html              # HTML template
│   └── favicon.ico             # App icon
│
├── src/
│   ├── index.js                # Entry point + Toaster
│   ├── App.js                  # Main application component
│   ├── App.css                 # Component styles
│   ├── index.css               # Global styles (Tailwind)
│   │
│   └── components/ui/          # Shadcn/UI components
│       ├── button.jsx          # Button component
│       ├── card.jsx            # Card layout
│       ├── input.jsx           # Input field
│       ├── label.jsx           # Form label
│       └── sonner.jsx          # Toast notifications
│
├── package.json                # Dependencies
├── tailwind.config.js          # Tailwind configuration
├── postcss.config.js           # PostCSS configuration
└── .env                        # Environment variables
```

---

## Key Components

### 1. App.js - Main Application

**Purpose**: Main upload interface with form validation and PDF generation.

**Features**:
- Child name input
- Photo upload with preview
- File validation (type, size)
- Loading states
- Success/error notifications
- Manual download button (browser compatibility)

**State Management**:
```javascript
const [childName, setChildName] = useState("");
const [selectedFile, setSelectedFile] = useState(null);
const [previewUrl, setPreviewUrl] = useState(null);
const [isGenerating, setIsGenerating] = useState(false);
const [generatedPdfUrl, setGeneratedPdfUrl] = useState(null);
const [pdfFilename, setPdfFilename] = useState("");
```

**Form Validation**:
```javascript
// Name validation
if (!childName.trim()) {
  toast.error("Please enter your child's name");
  return;
}

// File validation
const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
if (!allowedTypes.includes(file.type)) {
  toast.error("Please upload a valid image file");
  return;
}

if (file.size > 5 * 1024 * 1024) {
  toast.error("File size must be less than 5MB");
  return;
}
```

---

### 2. Upload Flow

**Step 1: File Selection**
```javascript
const handleFileChange = (e) => {
  const file = e.target.files[0];
  
  // Validate
  if (!allowedTypes.includes(file.type)) {
    toast.error("Invalid file type");
    return;
  }
  
  setSelectedFile(file);
  
  // Create preview
  const reader = new FileReader();
  reader.onloadend = () => {
    setPreviewUrl(reader.result);
  };
  reader.readAsDataURL(file);
};
```

**Step 2: Form Submission**
```javascript
const handleSubmit = async (e) => {
  e.preventDefault();
  setIsGenerating(true);
  
  const formData = new FormData();
  formData.append('name', childName.trim());
  formData.append('image', selectedFile);
  // Optional: formData.append('story_id', 'forest_of_smiles');
  
  try {
    const response = await axios.post(
      `${API}/generate`,
      formData,
      {
        headers: {'Content-Type': 'multipart/form-data'},
        responseType: 'blob'
      }
    );
    
    // Handle download
    handleDownload(response.data);
  } catch (error) {
    toast.error(error.response?.data?.detail || "Generation failed");
  } finally {
    setIsGenerating(false);
  }
};
```

**Step 3: Download Handling**
```javascript
const blob = new Blob([response.data], { type: 'application/pdf' });
const url = window.URL.createObjectURL(blob);
const filename = `${childName}_storybook.pdf`;

// Store for manual download button
setGeneratedPdfUrl(url);
setPdfFilename(filename);

// Attempt auto-download
const link = document.createElement('a');
link.href = url;
link.download = filename;
link.click();

toast.success("Storybook created! If download doesn't start, click the Download button.");
```

---

### 3. UI Components

#### Upload Interface

```jsx
<Card data-testid="story-generation-card">
  <CardHeader>
    <CardTitle>Create Your Story</CardTitle>
    <CardDescription>
      Upload your child's photo and enter their name
    </CardDescription>
  </CardHeader>
  
  <CardContent>
    <form onSubmit={handleSubmit}>
      {/* Name Input */}
      <Input
        data-testid="child-name-input"
        placeholder="Enter child's name"
        value={childName}
        onChange={(e) => setChildName(e.target.value)}
      />
      
      {/* File Upload */}
      <input
        data-testid="photo-upload-input"
        type="file"
        accept="image/*"
        onChange={handleFileChange}
      />
      
      {/* Preview */}
      {previewUrl && (
        <img src={previewUrl} data-testid="image-preview" />
      )}
      
      {/* Submit Button */}
      <Button
        data-testid="generate-story-button"
        type="submit"
        disabled={isGenerating}
      >
        {isGenerating ? "Creating..." : "Generate Storybook"}
      </Button>
    </form>
  </CardContent>
</Card>
```

#### Success Message with Download Button

```jsx
{generatedPdfUrl && (
  <div data-testid="download-success">
    <h3>✓ Storybook Created Successfully!</h3>
    
    {/* Manual Download Button (browser compatibility) */}
    <Button
      data-testid="manual-download-button"
      onClick={() => {
        const link = document.createElement('a');
        link.href = generatedPdfUrl;
        link.download = pdfFilename;
        link.click();
      }}
    >
      Download PDF
    </Button>
    
    {/* Reset Button */}
    <Button
      data-testid="create-another-button"
      variant="outline"
      onClick={() => {
        setChildName("");
        setSelectedFile(null);
        setPreviewUrl(null);
        setGeneratedPdfUrl(null);
        window.URL.revokeObjectURL(generatedPdfUrl);
      }}
    >
      Create Another Story
    </Button>
  </div>
)}
```

---

## Styling

### Tailwind CSS

**Configuration** (`tailwind.config.js`):
```javascript
module.exports = {
  content: ['./src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Custom colors
      }
    }
  },
  plugins: []
}
```

**Usage**:
```jsx
<div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-indigo-50 py-12 px-4">
  <Card className="shadow-lg border-blue-100">
    <Button className="w-full bg-blue-600 hover:bg-blue-700">
      Generate Storybook
    </Button>
  </Card>
</div>
```

### Design System

**Color Palette**:
- Primary: Light blue (#E0F2FE, #3B82F6)
- Accent: Indigo (#E0E7FF, #6366F1)
- Text: Gray scale (#1F2937, #6B7280)
- Success: Green (#10B981)
- Error: Red (#EF4444)

**Typography**:
- Headings: Font weight 700-800
- Body: Font weight 400
- Labels: Font weight 500-600

---

## API Integration

### Configuration

**Environment Variables** (`.env`):
```bash
REACT_APP_BACKEND_URL=https://tale-forge-66.preview.emergentagent.com
```

**Usage**:
```javascript
const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
```

### Axios Configuration

```javascript
import axios from 'axios';

// Generate storybook
const response = await axios.post(
  `${API}/generate`,
  formData,
  {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    responseType: 'blob',  // Important for file download
  }
);
```

---

## User Experience Features

### 1. Loading States

```jsx
<Button disabled={isGenerating}>
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
```

### 2. Toast Notifications

```javascript
import { toast } from 'sonner';

// Success
toast.success("Storybook created successfully!");

// Error
toast.error("Failed to generate storybook. Please try again.");

// Info
toast.info("Processing your request...");
```

### 3. Form Validation Feedback

```javascript
// Real-time validation
if (!childName.trim()) {
  toast.error("Please enter your child's name");
  return;
}

if (!selectedFile) {
  toast.error("Please upload a photo");
  return;
}
```

### 4. Image Preview

```jsx
{previewUrl && (
  <div>
    <img
      src={previewUrl}
      alt="Preview"
      className="w-32 h-32 object-cover rounded-full"
      data-testid="image-preview"
    />
    <Button onClick={() => {
      setSelectedFile(null);
      setPreviewUrl(null);
    }}>
      Remove Photo
    </Button>
  </div>
)}
```

---

## Browser Compatibility

### Download Issues (Edge, Safari)

**Problem**: Some browsers block automatic downloads.

**Solution**: Manual download button.

```javascript
// Automatic download (may not work in all browsers)
link.click();

// Manual download button (always works)
<Button onClick={() => {
  const link = document.createElement('a');
  link.href = generatedPdfUrl;
  link.download = pdfFilename;
  link.click();
}}>
  Download PDF
</Button>
```

**User Message**:
```
"Storybook created! If download doesn't start automatically, click the Download button below."
```

---

## Testing

### Component Tests

```javascript
import { render, screen, fireEvent } from '@testing-library/react';
import App from './App';

test('renders upload form', () => {
  render(<App />);
  expect(screen.getByTestId('child-name-input')).toBeInTheDocument();
  expect(screen.getByTestId('photo-upload-input')).toBeInTheDocument();
  expect(screen.getByTestId('generate-story-button')).toBeInTheDocument();
});

test('validates name input', () => {
  render(<App />);
  const button = screen.getByTestId('generate-story-button');
  fireEvent.click(button);
  // Should show error toast
});
```

### Integration Tests (Playwright)

See `/app/tests/integration/test_frontend_download.py`

---

## Performance

### Code Splitting

```javascript
import { lazy, Suspense } from 'react';

const HeavyComponent = lazy(() => import('./HeavyComponent'));

<Suspense fallback={<div>Loading...</div>}>
  <HeavyComponent />
</Suspense>
```

### Image Optimization

```javascript
// Compress before upload (future)
const compressImage = async (file) => {
  // Use browser-image-compression library
  const compressed = await imageCompression(file, options);
  return compressed;
};
```

---

## Accessibility

### ARIA Labels

```jsx
<input
  aria-label="Child's name"
  aria-required="true"
  aria-describedby="name-help"
/>

<Button
  aria-label="Generate personalized storybook"
  aria-busy={isGenerating}
>
  Generate Storybook
</Button>
```

### Keyboard Navigation

- Tab through form fields
- Enter to submit
- Escape to close modals

### Screen Reader Support

```jsx
<div role="alert" aria-live="polite">
  {error && <p>{error}</p>}
</div>
```

---

## Dependencies

```json
{
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^7.5.1",
    "axios": "^1.8.4",
    "sonner": "^2.0.3",
    "lucide-react": "^0.507.0",
    "@radix-ui/react-*": "latest"
  },
  "devDependencies": {
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0"
  }
}
```

---

## Development

### Running Locally

```bash
cd /app/frontend

# Install dependencies
yarn install

# Start development server
yarn start

# Build for production
yarn build
```

### Hot Reload

Changes to `src/**` auto-reload in browser.

---

## Best Practices

### DO
✅ Use data-testid for testing
✅ Validate inputs client-side
✅ Show loading states
✅ Provide clear error messages
✅ Handle download failures gracefully
✅ Clean up blob URLs
✅ Use environment variables for API URLs

### DON'T
❌ Hardcode API URLs
❌ Ignore error responses
❌ Skip loading states
❌ Forget to revoke blob URLs
❌ Use alert() for errors (use toast)
❌ Mix business logic in components

---

## Future Enhancements

### Planned
1. **Story Selection Dropdown** - Choose from multiple stories
2. **Preview Before Generate** - Show story preview
3. **Progress Indicator** - Show generation progress (1/10 pages)
4. **History** - View previously generated storybooks
5. **Sharing** - Email/social media sharing

### Possible
- User authentication
- Save favorites
- Custom story text
- Print service integration

---

## Summary

The `frontend/` provides:
- ✅ Clean, accessible upload interface
- ✅ Real-time validation
- ✅ Image preview
- ✅ Loading states
- ✅ Toast notifications
- ✅ Manual download fallback (browser compatibility)
- ✅ Responsive design
- ✅ Modern React practices

**Key Takeaway**: The frontend is the user's first impression. It's simple, clear, and handles edge cases (download failures) gracefully to ensure a smooth experience.
