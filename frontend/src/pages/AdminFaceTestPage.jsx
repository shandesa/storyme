/**
 * AdminFaceTestPage.jsx
 * ─────────────────────
 * Face blend quality testing dashboard.
 * Route: /admin/face-test
 *
 * UX pattern:
 *   • Same auth gate as AdminOrdersPage (X-Admin-Key, stored in sessionStorage
 *     so navigating between admin tabs doesn't require re-login).
 *   • Shared admin nav bar linking to /admin/orders and /admin/face-test.
 *   • Upload 4 child photos → backend runs blend quality test → show per-page
 *     metric grid with A/B/C/D grades and expandable suggestions.
 *   • Download full JSON report for Claude-based parameter tuning.
 */

import { useState, useRef, useCallback } from "react";
import { useNavigate }                   from "react-router-dom";
import axios                             from "axios";
import { toast }                         from "sonner";
import { Button }    from "@/components/ui/button";
import { Input }     from "@/components/ui/input";
import { Label }     from "@/components/ui/label";
import { Badge }     from "@/components/ui/badge";
import { Progress }  from "@/components/ui/progress";
import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Loader2, Lock, FlaskConical, Package,
  Upload, CheckCircle2, AlertTriangle, XCircle,
  Download, ChevronDown, ChevronUp, Image as ImgIcon,
} from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const API     = `${BACKEND}/api/admin`;

// ─── Grade badge colours ──────────────────────────────────────────────────────
const GRADE_STYLE = {
  A: "bg-emerald-100 text-emerald-700 border-emerald-200",
  B: "bg-blue-100   text-blue-700   border-blue-200",
  C: "bg-amber-100  text-amber-700  border-amber-200",
  D: "bg-red-100    text-red-700    border-red-200",
};

const GRADE_ICON = {
  A: <CheckCircle2 className="w-3.5 h-3.5" />,
  B: <CheckCircle2 className="w-3.5 h-3.5" />,
  C: <AlertTriangle className="w-3.5 h-3.5" />,
  D: <XCircle className="w-3.5 h-3.5" />,
};

function GradeBadge({ grade }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold border ${GRADE_STYLE[grade] || ""}`}>
      {GRADE_ICON[grade]} {grade}
    </span>
  );
}

function ScoreBar({ score }) {
  const pct = Math.round((score || 0) * 100);
  const col  = pct >= 85 ? "bg-emerald-500" : pct >= 70 ? "bg-blue-500" : pct >= 55 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-gray-700">
        <div className={`h-full rounded-full ${col}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-8 text-right">{pct}%</span>
    </div>
  );
}

// ─── Admin nav (shared with AdminOrdersPage via localStorage key) ─────────────
function AdminNav({ active }) {
  return (
    <div className="flex gap-1 mb-6 bg-gray-900 rounded-lg p-1 w-fit">
      <a href="/admin/orders"
        className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors
          ${active === "orders"
            ? "bg-gray-800 text-white"
            : "text-gray-400 hover:text-white hover:bg-gray-800/60"}`}>
        <Package className="w-4 h-4" /> Orders
      </a>
      <a href="/admin/face-test"
        className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors
          ${active === "face-test"
            ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
            : "text-gray-400 hover:text-white hover:bg-gray-800/60"}`}>
        <FlaskConical className="w-4 h-4" /> Face Quality Test
      </a>
    </div>
  );
}

// ─── Face upload card ─────────────────────────────────────────────────────────
function FaceUploadCard({ index, file, onFile }) {
  const ref = useRef();
  const preview = file ? URL.createObjectURL(file) : null;

  return (
    <div
      onClick={() => ref.current?.click()}
      className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed cursor-pointer transition-colors h-36
        ${file ? "border-amber-500/60 bg-amber-500/5" : "border-gray-700 hover:border-gray-500 bg-gray-900"}`}
    >
      <input
        ref={ref} type="file" className="hidden"
        accept="image/jpeg,image/png,image/webp"
        onChange={e => onFile(e.target.files[0] || null)}
      />
      {preview ? (
        <img src={preview} alt={`Face ${index + 1}`}
          className="h-full w-full object-cover rounded-xl opacity-80" />
      ) : (
        <>
          <Upload className="w-6 h-6 text-gray-600 mb-1" />
          <span className="text-xs text-gray-500">Face {index + 1}</span>
        </>
      )}
      {file && (
        <div className="absolute top-1 right-1 bg-amber-500 rounded-full w-4 h-4 flex items-center justify-center">
          <CheckCircle2 className="w-3 h-3 text-white" />
        </div>
      )}
    </div>
  );
}

// ─── Per-page result card ─────────────────────────────────────────────────────
function PageResultCard({ pageData, adminKey, jobId }) {
  const [expanded, setExpanded] = useState(false);
  const [lightbox, setLightbox] = useState(null);

  const grade = pageData.by_face?.[0]?.metrics?.grade;

  return (
    <Card className="bg-gray-900 border-gray-800 overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-800/40"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="w-8 h-8 rounded-full bg-gray-800 flex items-center justify-center text-xs font-bold text-gray-300">
          {pageData.page_number}
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white">Page {pageData.page_number}</span>
            <Badge className="bg-gray-800 text-gray-400 text-xs border-0">
              {pageData.expression || "neutral"}
            </Badge>
            {grade && <GradeBadge grade={grade} />}
          </div>
          {pageData.by_face?.[0]?.metrics?.overall_score !== undefined && (
            <div className="w-48 mt-1">
              <ScoreBar score={pageData.by_face[0].metrics.overall_score} />
            </div>
          )}
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-500" /> : <ChevronDown className="w-4 h-4 text-gray-500" />}
      </div>

      {/* Expanded */}
      {expanded && (
        <div className="border-t border-gray-800 px-4 py-4 space-y-4">
          {/* 4-face image grid */}
          <div className="grid grid-cols-4 gap-2">
            {pageData.by_face?.map((fd, fi) => (
              <div key={fi} className="space-y-1">
                <div
                  className="aspect-square rounded-lg overflow-hidden bg-gray-800 cursor-zoom-in"
                  onClick={() => setLightbox(fd.image_url)}
                >
                  {fd.image_url ? (
                    <img
                      src={`${BACKEND}${fd.image_url}?key=${encodeURIComponent(adminKey)}`}
                      alt={`Face ${fi + 1} page ${pageData.page_number}`}
                      className="w-full h-full object-cover"
                      onError={e => { e.target.style.display = "none"; }}
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <ImgIcon className="w-5 h-5 text-gray-600" />
                    </div>
                  )}
                </div>
                {fd.metrics?.grade && <GradeBadge grade={fd.metrics.grade} />}
              </div>
            ))}
          </div>

          {/* Metrics table for first face */}
          {pageData.by_face?.[0]?.metrics && (() => {
            const m = pageData.by_face[0].metrics;
            const rows = [
              { label: "Face position",   score: m.face_position_score,         note: `IoU` },
              { label: "Edge quality",    score: m.edge_quality_score,           note: m.edge_quality_label },
              { label: "Lighting match",  score: m.lighting_consistency_score,   note: `ΔL ${m.lighting_delta_lab_L?.toFixed(1)}` },
              { label: "Colour harmony",  score: m.colour_harmony_score,         note: `corr ${m.histogram_correlation?.toFixed(2)}` },
              { label: "Skin blend",      score: m.skin_blend_score,             note: `Δ ${m.skin_tone_delta_rgb?.toFixed(1)}` },
            ];
            return (
              <div className="rounded-lg bg-gray-800/60 overflow-hidden">
                <div className="px-3 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide border-b border-gray-700">
                  Quality Metrics (face 1)
                </div>
                {rows.map(r => (
                  <div key={r.label} className="flex items-center gap-3 px-3 py-2 border-b border-gray-700/50 last:border-0">
                    <span className="text-xs text-gray-400 w-28 shrink-0">{r.label}</span>
                    <div className="flex-1"><ScoreBar score={r.score} /></div>
                    <span className="text-xs text-gray-500 w-24 text-right">{r.note}</span>
                  </div>
                ))}
              </div>
            );
          })()}

          {/* Issues + suggestions */}
          {pageData.by_face?.[0]?.issues?.length > 0 && (
            <div className="space-y-1.5">
              {pageData.by_face[0].issues.map((issue, i) => (
                <div key={i} className="flex items-start gap-2 text-xs text-amber-400 bg-amber-500/10 rounded-md px-3 py-2">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  {issue}
                </div>
              ))}
            </div>
          )}

          {pageData.by_face?.[0]?.suggestions &&
            Object.keys(pageData.by_face[0].suggestions).length > 0 && (
            <div className="rounded-md bg-gray-800 px-3 py-2">
              <p className="text-xs text-gray-500 uppercase mb-1 tracking-wide">Suggested tweaks</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(pageData.by_face[0].suggestions).map(([k, v]) => (
                  <span key={k} className="bg-gray-700 text-gray-300 text-xs px-2 py-0.5 rounded font-mono">
                    {k}: {String(v)}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Lightbox */}
      <Dialog open={!!lightbox} onOpenChange={() => setLightbox(null)}>
        <DialogContent className="max-w-2xl bg-gray-900 border-gray-800 p-2">
          <DialogHeader className="px-2 pt-2">
            <DialogTitle className="text-white text-sm">Page {pageData.page_number} preview</DialogTitle>
          </DialogHeader>
          {lightbox && (
            <img
              src={`${BACKEND}${lightbox}?key=${encodeURIComponent(adminKey)}`}
              alt="Preview"
              className="w-full rounded-lg"
            />
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function AdminFaceTestPage() {
  // Auth (persisted to sessionStorage so tab-switching doesn't re-prompt)
  const [adminKey,  setAdminKey]  = useState(() => sessionStorage.getItem("adminKey") || "");
  const [authed,    setAuthed]    = useState(() => !!sessionStorage.getItem("adminKey"));
  const [authError, setAuthError] = useState("");

  // Upload
  const [faces,    setFaces]    = useState([null, null, null, null]);
  const [storyId,  setStoryId]  = useState("forest_of_smiles");

  // Job
  const [jobId,    setJobId]    = useState(null);
  const [job,      setJob]      = useState(null);
  const [polling,  setPolling]  = useState(false);

  // Results
  const [report,   setReport]   = useState(null);

  // ── Auth ────────────────────────────────────────────────────────────────────
  const handleAuth = async (e) => {
    e.preventDefault();
    if (!adminKey.trim()) { setAuthError("Enter admin key"); return; }
    try {
      await axios.get(`${BACKEND}/api/v2/admin/orders?limit=1`,
        { headers: { "X-Admin-Key": adminKey.trim() } });
      sessionStorage.setItem("adminKey", adminKey.trim());
      setAuthed(true);
      setAuthError("");
    } catch (err) {
      setAuthError(err.response?.data?.detail || "Invalid admin key");
    }
  };

  // ── Job polling ─────────────────────────────────────────────────────────────
  const pollJob = useCallback(async (id, key) => {
    setPolling(true);
    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`${API}/face-test/job/${id}`,
          { headers: { "X-Admin-Key": key } });
        setJob(res.data);
        if (res.data.status === "done") {
          clearInterval(interval);
          setPolling(false);
          setReport(res.data.results);
          toast.success("Quality test complete!");
        } else if (res.data.status === "error") {
          clearInterval(interval);
          setPolling(false);
          toast.error(res.data.error || "Job failed");
        }
      } catch {
        clearInterval(interval);
        setPolling(false);
        toast.error("Lost connection to job");
      }
    }, 3000);
  }, []);

  // ── Submit ──────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    const missing = faces.filter(f => !f);
    if (missing.length) {
      toast.error(`Upload all 4 face photos (${missing.length} missing)`);
      return;
    }
    setReport(null);
    setJob(null);

    const fd = new FormData();
    fd.append("story_id", storyId);
    faces.forEach((f, i) => fd.append(`face_${i + 1}`, f));

    try {
      const res = await axios.post(`${API}/face-test/run`, fd, {
        headers: { "X-Admin-Key": adminKey, "Content-Type": "multipart/form-data" },
      });
      setJobId(res.data.job_id);
      setJob({ status: "running", progress: 0, total: res.data.total_steps });
      toast.success("Job submitted — running…");
      pollJob(res.data.job_id, adminKey);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Submit failed");
    }
  };

  // ── Download report ─────────────────────────────────────────────────────────
  const downloadReport = () => {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `face_quality_report_${jobId?.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── Login screen ────────────────────────────────────────────────────────────
  if (!authed) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
        <Card className="w-full max-w-sm bg-gray-900 border-gray-800 shadow-2xl">
          <CardHeader className="text-center pb-2">
            <Lock className="w-8 h-8 text-amber-500 mx-auto mb-2" />
            <CardTitle className="text-white text-lg">StoryMe Admin</CardTitle>
            <p className="text-gray-400 text-sm">Face Quality Test</p>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-gray-300 text-sm">Admin Key</Label>
                <Input
                  type="password"
                  placeholder="Enter ADMIN_SECRET_KEY"
                  value={adminKey}
                  onChange={e => setAdminKey(e.target.value)}
                  className="bg-gray-800 border-gray-700 text-white placeholder:text-gray-600"
                  autoFocus
                  onKeyDown={e => e.key === "Enter" && handleAuth(e)}
                />
                {authError && <p className="text-red-400 text-xs">{authError}</p>}
              </div>
              <Button onClick={handleAuth} className="w-full bg-amber-500 hover:bg-amber-600 text-white">
                Sign In
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ── Dashboard ────────────────────────────────────────────────────────────────
  const progress  = job ? Math.round((job.progress / Math.max(1, job.total)) * 100) : 0;
  const isRunning = job?.status === "running";

  return (
    <div className="min-h-screen bg-gray-950 px-4 py-6 text-white">
      <div className="max-w-5xl mx-auto">

        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-2xl font-bold text-white">Face Quality Test</h1>
            <p className="text-gray-400 text-sm">StoryMe Admin · Blend accuracy evaluator</p>
          </div>
          {report && (
            <Button onClick={downloadReport} variant="outline" size="sm"
              className="border-gray-700 text-gray-300 hover:bg-gray-800">
              <Download className="w-4 h-4 mr-1.5" /> Report JSON
            </Button>
          )}
        </div>

        {/* Nav */}
        <AdminNav active="face-test" />

        {/* Aggregate score (post-run) */}
        {report?.aggregate && (
          <div className="grid grid-cols-3 gap-3 mb-5">
            {[
              { label: "Mean score", value: `${(report.aggregate.mean_overall_score * 100).toFixed(0)}%` },
              { label: "Grade", value: report.aggregate.grade },
              { label: "Pages tested", value: report.report_meta?.pages_evaluated },
            ].map(({ label, value }) => (
              <div key={label} className="bg-gray-900 rounded-lg border border-gray-800 p-3 text-center">
                <p className="text-2xl font-black text-amber-400">{value}</p>
                <p className="text-xs text-gray-500 mt-0.5">{label}</p>
              </div>
            ))}
          </div>
        )}

        <div className="grid lg:grid-cols-[340px_1fr] gap-5">

          {/* ── Left: controls ────────────────────────────────────────────── */}
          <div className="space-y-4">
            <Card className="bg-gray-900 border-gray-800">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-gray-300 flex items-center gap-2">
                  <FlaskConical className="w-4 h-4 text-amber-500" /> Test Setup
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Story selector */}
                <div className="space-y-1.5">
                  <Label className="text-gray-400 text-xs uppercase tracking-wide">Story</Label>
                  <select
                    value={storyId}
                    onChange={e => setStoryId(e.target.value)}
                    disabled={isRunning}
                    className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white"
                  >
                    <option value="forest_of_smiles">Forest of Smiles</option>
                  </select>
                </div>

                {/* Face uploads */}
                <div className="space-y-1.5">
                  <Label className="text-gray-400 text-xs uppercase tracking-wide">
                    Child Photos (4 test faces)
                  </Label>
                  <div className="grid grid-cols-2 gap-2">
                    {faces.map((f, i) => (
                      <FaceUploadCard key={i} index={i} file={f}
                        onFile={file => setFaces(prev => {
                          const next = [...prev]; next[i] = file; return next;
                        })} />
                    ))}
                  </div>
                  <p className="text-xs text-gray-600">
                    {faces.filter(Boolean).length} / 4 photos uploaded
                  </p>
                </div>

                <Button
                  onClick={handleSubmit}
                  disabled={isRunning || faces.filter(Boolean).length < 4}
                  className="w-full bg-amber-500 hover:bg-amber-600 text-white"
                >
                  {isRunning
                    ? <><Loader2 className="w-4 h-4 animate-spin mr-2" />Running…</>
                    : <><FlaskConical className="w-4 h-4 mr-2" />Run Quality Test</>}
                </Button>

                {/* Progress */}
                {isRunning && (
                  <div className="space-y-1.5">
                    <Progress value={progress} className="h-1.5 bg-gray-800" />
                    <p className="text-xs text-gray-500 text-right">
                      {job?.progress || 0} / {job?.total || "?"} steps
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Claude tuning prompt */}
            {report?.claude_tuning_prompt && (
              <Card className="bg-gray-900 border-amber-800/40">
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs text-amber-400 uppercase tracking-wide">
                    Claude Tuning Prompt
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-gray-400 leading-relaxed mb-3">
                    Paste this into Claude to get specific code-level improvements:
                  </p>
                  <div className="bg-gray-800 rounded-md p-2 max-h-28 overflow-y-auto">
                    <p className="text-xs text-gray-300 font-mono leading-relaxed break-words">
                      {report.claude_tuning_prompt}
                    </p>
                  </div>
                  <Button
                    size="sm" variant="outline"
                    className="mt-2 w-full border-gray-700 text-gray-300 hover:bg-gray-800 text-xs"
                    onClick={() => {
                      navigator.clipboard.writeText(report.claude_tuning_prompt);
                      toast.success("Copied to clipboard");
                    }}
                  >
                    Copy prompt
                  </Button>
                </CardContent>
              </Card>
            )}
          </div>

          {/* ── Right: results grid ───────────────────────────────────────── */}
          <div className="space-y-3">
            {!report && !isRunning && (
              <div className="flex flex-col items-center justify-center h-64 text-gray-600 border border-gray-800 rounded-xl">
                <FlaskConical className="w-10 h-10 mb-3 opacity-40" />
                <p className="text-sm">Upload 4 photos and run the test</p>
                <p className="text-xs mt-1 opacity-70">Results will appear here</p>
              </div>
            )}

            {isRunning && (
              <div className="flex flex-col items-center justify-center h-64 text-gray-500">
                <Loader2 className="w-8 h-8 animate-spin mb-3 text-amber-500" />
                <p className="text-sm">Processing pages…</p>
                <p className="text-xs mt-1 text-gray-600">
                  Blend → evaluate → score each page × 4 faces
                </p>
              </div>
            )}

            {report?.pages?.map(page => (
              <PageResultCard
                key={page.page_number}
                pageData={page}
                adminKey={adminKey}
                jobId={jobId}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
