/**
 * KidProfilesPage.jsx
 * ────────────────────
 * Full CRUD page for managing kid profiles.
 * Route: /profiles
 *
 * This page is NOT the home profile selector — it is the dedicated management
 * screen reached from the home page "Manage Profiles" link.
 *
 * Features:
 *  • List all profiles with avatar, name, age, gender
 *  • Create new profile (name, gender, age, notes, optional photo)
 *  • Edit existing profile metadata
 *  • Replace profile photo
 *  • Delete profile (with confirmation)
 */

import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button }  from "@/components/ui/button";
import { Input }   from "@/components/ui/input";
import { Label }   from "@/components/ui/label";
import { Badge }   from "@/components/ui/badge";
import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  ArrowLeft, Plus, Pencil, Trash2, Upload, User,
  Loader2, CheckCircle, X,
} from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const API     = `${BACKEND}/api/v2/kids`;

const GENDER_LABELS = { male: "Boy", female: "Girl", neutral: "Neutral" };
const GENDER_COLORS = {
  male:    "bg-blue-100 text-blue-700",
  female:  "bg-pink-100 text-pink-700",
  neutral: "bg-gray-100 text-gray-600",
};

function authHeader() {
  const token = sessionStorage.getItem("storyme_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ─── Avatar component ─────────────────────────────────────────────────────────
function ProfileAvatar({ profile, size = 56 }) {
  const [err, setErr] = useState(false);
  const src = profile.has_photo && !err
    ? `${BACKEND}${profile.photo_url}?token=${sessionStorage.getItem("storyme_token") || ""}`
    : null;

  return (
    <div
      className="rounded-full flex items-center justify-center bg-emerald-100 text-emerald-700 font-bold flex-shrink-0 overflow-hidden"
      style={{ width: size, height: size, fontSize: size * 0.4 }}
    >
      {src ? (
        <img
          src={src}
          alt={profile.name}
          className="w-full h-full object-cover"
          onError={() => setErr(true)}
        />
      ) : (
        profile.name?.[0]?.toUpperCase() || <User className="w-5 h-5" />
      )}
    </div>
  );
}

// ─── Profile card ─────────────────────────────────────────────────────────────
function ProfileCard({ profile, onEdit, onDelete }) {
  return (
    <Card className="border border-gray-200 shadow-sm">
      <CardContent className="p-4">
        <div className="flex items-center gap-3">
          <ProfileAvatar profile={profile} size={52} />
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-gray-800 truncate">{profile.name}</p>
            <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
              <Badge className={`text-xs border-0 ${GENDER_COLORS[profile.gender] || GENDER_COLORS.neutral}`}>
                {GENDER_LABELS[profile.gender] || profile.gender}
              </Badge>
              {profile.age > 0 && (
                <span className="text-xs text-gray-500">{profile.age} yrs</span>
              )}
            </div>
            {profile.notes && (
              <p className="text-xs text-gray-400 mt-0.5 truncate">{profile.notes}</p>
            )}
          </div>
          <div className="flex gap-1 flex-shrink-0">
            <Button size="sm" variant="ghost" onClick={() => onEdit(profile)}
              className="h-8 w-8 p-0 text-gray-500 hover:text-emerald-600">
              <Pencil className="w-3.5 h-3.5" />
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onDelete(profile)}
              className="h-8 w-8 p-0 text-gray-500 hover:text-red-500">
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Profile form (create / edit) ────────────────────────────────────────────
function ProfileForm({ profile, onSave, onCancel }) {
  const [name,    setName]    = useState(profile?.name   || "");
  const [gender,  setGender]  = useState(profile?.gender || "neutral");
  const [age,     setAge]     = useState(profile?.age > 0 ? String(profile.age) : "");
  const [notes,   setNotes]   = useState(profile?.notes  || "");
  const [photo,   setPhoto]   = useState(null);
  const [preview, setPreview] = useState(null);
  const [saving,  setSaving]  = useState(false);
  const fileRef = useRef();

  const handlePhoto = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    setPhoto(f);
    const reader = new FileReader();
    reader.onloadend = () => setPreview(reader.result);
    reader.readAsDataURL(f);
  };

  const handleSubmit = async () => {
    if (!name.trim()) { toast.error("Name is required"); return; }
    setSaving(true);
    try {
      const headers = authHeader();

      if (profile) {
        // Update metadata
        await axios.put(`${API}/${profile.profile_id}`,
          { name: name.trim(), gender, age: age ? parseInt(age) : null, notes: notes.trim() },
          { headers },
        );
        // Update photo if new one chosen
        if (photo) {
          const fd = new FormData(); fd.append("photo", photo);
          await axios.post(`${API}/${profile.profile_id}/photo`, fd, { headers });
        }
        toast.success("Profile updated!");
      } else {
        // Create new
        const fd = new FormData();
        fd.append("name",   name.trim());
        fd.append("gender", gender);
        if (age)   fd.append("age",   age);
        if (notes) fd.append("notes", notes.trim());
        if (photo) fd.append("photo", photo);
        await axios.post(API, fd, { headers });
        toast.success("Profile created!");
      }
      onSave();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Save failed. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="border-2 border-emerald-200 shadow-md">
      <CardHeader className="pb-3">
        <CardTitle className="text-base text-gray-800">
          {profile ? `Edit ${profile.name}'s Profile` : "New Kid Profile"}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Photo */}
        <div className="flex items-center gap-4">
          <div
            onClick={() => fileRef.current?.click()}
            className="w-16 h-16 rounded-full bg-gray-100 border-2 border-dashed border-gray-300 flex items-center justify-center cursor-pointer hover:border-emerald-400 overflow-hidden flex-shrink-0"
          >
            {preview ? (
              <img src={preview} alt="preview" className="w-full h-full object-cover" />
            ) : profile?.has_photo ? (
              <img
                src={`${BACKEND}${profile.photo_url}?token=${sessionStorage.getItem("storyme_token") || ""}`}
                alt={profile.name}
                className="w-full h-full object-cover"
              />
            ) : (
              <Upload className="w-5 h-5 text-gray-400" />
            )}
          </div>
          <div>
            <p className="text-sm font-medium text-gray-700">
              {profile?.has_photo ? "Change photo" : "Add photo (optional)"}
            </p>
            <p className="text-xs text-gray-400">JPG, PNG, WEBP — max 5MB</p>
            <input ref={fileRef} type="file" className="hidden"
              accept="image/jpeg,image/png,image/webp" onChange={handlePhoto} />
          </div>
        </div>

        {/* Name */}
        <div className="space-y-1">
          <Label className="text-gray-700 text-sm">Child's Name *</Label>
          <Input value={name} onChange={e => setName(e.target.value)}
            placeholder="Enter name" maxLength={60} className="border-gray-300" />
        </div>

        {/* Gender */}
        <div className="space-y-1">
          <Label className="text-gray-700 text-sm">Gender *</Label>
          <Select value={gender} onValueChange={setGender}>
            <SelectTrigger className="border-gray-300"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="neutral">Neutral</SelectItem>
              <SelectItem value="male">Boy (Male)</SelectItem>
              <SelectItem value="female">Girl (Female)</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Age */}
        <div className="space-y-1">
          <Label className="text-gray-700 text-sm">Age (optional, 0–12)</Label>
          <Input value={age} onChange={e => setAge(e.target.value)}
            placeholder="e.g. 5" type="number" min="0" max="12"
            className="border-gray-300" />
        </div>

        {/* Notes */}
        <div className="space-y-1">
          <Label className="text-gray-700 text-sm">Notes (optional)</Label>
          <Input value={notes} onChange={e => setNotes(e.target.value)}
            placeholder="e.g. Loves dinosaurs" maxLength={200}
            className="border-gray-300" />
        </div>

        <div className="flex gap-2 pt-1">
          <Button onClick={handleSubmit} disabled={saving}
            className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white">
            {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <CheckCircle className="w-4 h-4 mr-1" />}
            {profile ? "Save Changes" : "Create Profile"}
          </Button>
          <Button onClick={onCancel} variant="outline" disabled={saving}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function KidProfilesPage() {
  const navigate  = useNavigate();
  const [profiles,  setProfiles]  = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [showForm,  setShowForm]  = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [delTarget,  setDelTarget]  = useState(null);
  const [deleting,   setDeleting]   = useState(false);
  const MAX = 5;

  const load = async () => {
    setLoading(true);
    try {
      const res = await axios.get(API, { headers: authHeader() });
      setProfiles(res.data.profiles || []);
    } catch {
      toast.error("Failed to load profiles.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleEdit = (p) => { setEditTarget(p); setShowForm(true); };
  const handleNew  = () => { setEditTarget(null); setShowForm(true); };
  const handleSaved = () => { setShowForm(false); setEditTarget(null); load(); };
  const handleCancel = () => { setShowForm(false); setEditTarget(null); };

  const handleDelete = async () => {
    if (!delTarget) return;
    setDeleting(true);
    try {
      await axios.delete(`${API}/${delTarget.profile_id}`, { headers: authHeader() });
      toast.success(`${delTarget.name}'s profile deleted.`);
      setDelTarget(null);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Delete failed.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-white to-emerald-50 py-8 px-4">
      <div className="max-w-lg mx-auto">

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <Button variant="ghost" size="sm" onClick={() => navigate("/home")}
            className="text-gray-500 hover:text-gray-700 -ml-2">
            <ArrowLeft className="w-4 h-4 mr-1" />Back
          </Button>
          <div>
            <h1 className="text-xl font-bold text-gray-800">Kid Profiles</h1>
            <p className="text-xs text-gray-500">
              {profiles.length}/{MAX} profiles · Save photos to skip re-uploading
            </p>
          </div>
        </div>

        {/* Form */}
        {showForm && (
          <div className="mb-4">
            <ProfileForm
              profile={editTarget}
              onSave={handleSaved}
              onCancel={handleCancel}
            />
          </div>
        )}

        {/* Profile list */}
        {loading ? (
          <div className="flex items-center justify-center h-32 text-gray-400">
            <Loader2 className="w-6 h-6 animate-spin mr-2" /> Loading profiles…
          </div>
        ) : (
          <div className="space-y-3">
            {profiles.map(p => (
              <ProfileCard key={p.profile_id} profile={p}
                onEdit={handleEdit} onDelete={setDelTarget} />
            ))}

            {profiles.length === 0 && !showForm && (
              <div className="text-center py-10 text-gray-400">
                <User className="w-10 h-10 mx-auto mb-2 opacity-40" />
                <p className="text-sm">No profiles yet.</p>
                <p className="text-xs">Add a profile to save your child's photo.</p>
              </div>
            )}

            {profiles.length < MAX && !showForm && (
              <Button onClick={handleNew} variant="outline"
                className="w-full border-dashed border-2 border-emerald-300 text-emerald-600 hover:bg-emerald-50 py-5">
                <Plus className="w-4 h-4 mr-2" />Add Kid Profile
              </Button>
            )}
          </div>
        )}

        {/* Delete confirmation */}
        {delTarget && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
            <Card className="w-full max-w-sm shadow-xl">
              <CardContent className="pt-6 space-y-4">
                <div className="flex items-center gap-3">
                  <ProfileAvatar profile={delTarget} size={44} />
                  <div>
                    <p className="font-semibold text-gray-800">Delete {delTarget.name}'s Profile?</p>
                    <p className="text-xs text-gray-500">
                      This will permanently delete the profile and photo.
                      Previously generated books are not affected.
                    </p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button onClick={handleDelete} disabled={deleting}
                    className="flex-1 bg-red-500 hover:bg-red-600 text-white">
                    {deleting ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Trash2 className="w-4 h-4 mr-1" />}
                    Delete
                  </Button>
                  <Button onClick={() => setDelTarget(null)} variant="outline" disabled={deleting}>
                    Cancel
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
