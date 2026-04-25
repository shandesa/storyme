/**
 * TermsPage — shown once, on first login, before the user reaches /home.
 *
 * Flow:
 *   • Receives { mobile } via React Router location.state
 *   • Renders scrollable T&C with Accept / Decline buttons
 *   • Accept  → POST /api/auth/accept-terms → navigate to /home
 *   • Decline → POST /api/auth/accept-terms (accepted=false)
 *              → toast warning → navigate to / (login)
 *
 * The Accept button is only enabled once the user has scrolled to the bottom
 * of the terms panel (acknowledges they've read it).
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  BookOpen,
  Shield,
  Camera,
  HardDrive,
  Image,
  CheckCircle2,
  XCircle,
  ChevronDown,
  Loader2,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { acceptTerms } from "@/api/auth";

// ─── T&C content (mirrors docs/legal/TERMS_AND_CONDITIONS.md) ─────────────────

const SECTIONS = [
  {
    icon: BookOpen,
    title: "1. Agreement to Terms",
    body: `By creating an account, accessing, or using the StoryMe platform ("Service"), you agree to be bound by these Terms and Conditions. If you do not agree, you must not use the Service. StoryMe reserves the right to update these Terms at any time. Continued use of the Service following notification of changes constitutes your acceptance of the revised Terms.`,
  },
  {
    icon: BookOpen,
    title: "2. Description of Service",
    body: `StoryMe is a personalised children's storybook generation platform that creates illustrated storybooks featuring a child's likeness as the main character. The Service uses artificial intelligence to generate personalised story content and cartoon-style illustrations tailored to the child whose image is provided by the user.`,
  },
  {
    icon: Shield,
    title: "3. Eligibility",
    body: `You must be at least 18 years of age to create an account. By using the Service you represent that you are at least 18, that you have the legal authority to provide consent on behalf of any child whose image or information you submit, and that you are the parent or legal guardian of any child whose likeness is used in the storybook generation process.`,
  },
  {
    icon: Camera,
    title: "4. Child Image — Collection and Use",
    highlight: true,
    body: `IMPORTANT: The photograph you upload will be used exclusively for the purpose of generating the cartoon or illustrated character that appears within the personalised storybook. Your child's image will NOT be used for any other commercial, marketing, training, research, or third-party purposes. Your uploaded child photographs will NOT be used to train, fine-tune, or improve any AI or machine learning model. Your child's photograph will not be sold, licensed, transferred, or shared with any third party outside of the strictly necessary technical service providers required to operate the platform.`,
  },
  {
    icon: HardDrive,
    title: "5. Storage for Caching Purposes",
    highlight: true,
    body: `By using the Service, you explicitly consent to the following: Your uploaded photograph will be stored securely on our cloud infrastructure (Microsoft Azure Blob Storage) to avoid repeated image processing and improve performance. Processed and intermediate image data (including face-blended and cartoonised versions) may be retained in our cache store. Uploaded images and cached data will be retained for a maximum of 12 months from the date of last account activity. Upon a valid deletion request, all originals and cached derivatives of the uploaded image will be permanently deleted within 30 days.`,
  },
  {
    icon: Image,
    title: "6. Cover Page Cartoonised Image",
    highlight: true,
    body: `You explicitly consent to the placement of a cartoonised, illustrated, or AI-stylised version of the child's photograph on the cover page and relevant interior pages of the generated storybook. The image used in the storybook is an artistic, cartoon-style rendering derived from the uploaded photograph — it is not a photographic reproduction. The personalised storybook is provided to you for personal, non-commercial use only.`,
  },
  {
    icon: Shield,
    title: "7. User Responsibilities",
    body: `You agree to only upload images of children for whom you are the parent or legal guardian. You agree not to upload images containing nudity, inappropriate content, or content that violates any applicable law. You agree not to upload images of children who are not in your lawful care. We reserve the right to suspend or terminate your account if you violate these Terms.`,
  },
  {
    icon: Shield,
    title: "8. Data Protection and Privacy",
    body: `Our collection and use of personal data is governed by our Privacy Policy, which forms part of these Terms. We act as a data controller and are committed to complying with applicable data protection laws. You have the right to access, correct, or request erasure of your personal data at any time by contacting privacy@storyme.app.`,
  },
  {
    icon: Shield,
    title: "9. Limitation of Liability",
    body: `The Service is provided on an "as is" basis. We make no warranties regarding the accuracy, reliability, or availability of the Service. Our total liability for any claim shall not exceed the amount you paid to us in the 12 months preceding the claim, or INR 1,000 (or equivalent), whichever is greater.`,
  },
  {
    icon: Shield,
    title: "10. Governing Law",
    body: `These Terms shall be governed by the laws of India. Any dispute shall first be subject to good-faith negotiation. If unresolved within 30 days, disputes shall be submitted to binding arbitration under the Arbitration and Conciliation Act, 1996. For questions, contact us at legal@storyme.app.`,
  },
];

// ─── helpers ──────────────────────────────────────────────────────────────────

function SectionCard({ section, index }) {
  const Icon = section.icon;
  return (
    <div
      className={[
        "rounded-2xl p-5 mb-4 border transition-all",
        section.highlight
          ? "border-amber-200 bg-amber-50/60"
          : "border-slate-100 bg-white/70",
      ].join(" ")}
    >
      <div className="flex items-start gap-3">
        <div
          className={[
            "mt-0.5 flex-shrink-0 rounded-lg p-1.5",
            section.highlight ? "bg-amber-100 text-amber-600" : "bg-indigo-50 text-indigo-500",
          ].join(" ")}
        >
          <Icon size={16} />
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-800 mb-1">{section.title}</p>
          <p className="text-sm text-slate-600 leading-relaxed">{section.body}</p>
        </div>
      </div>
    </div>
  );
}

// ─── component ────────────────────────────────────────────────────────────────

export default function TermsPage() {
  const location = useLocation();
  const navigate = useNavigate();

  const mobile = location.state?.mobile ?? null;

  const [hasScrolledToBottom, setHasScrolledToBottom] = useState(false);
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  // Guard: if no mobile state, redirect to login
  useEffect(() => {
    if (!mobile) {
      toast.error("Session expired. Please log in again.");
      navigate("/", { replace: true });
    }
  }, [mobile, navigate]);

  // Track scroll position to enable the Accept button
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    if (nearBottom) setHasScrolledToBottom(true);
  }, []);

  // ── Accept ─────────────────────────────────────────────────────────────────

  const handleAccept = async () => {
    setLoading(true);
    const result = await acceptTerms(mobile, true);
    setLoading(false);

    if (result.error) {
      toast.error(result.message || "Something went wrong. Please try again.");
      return;
    }

    toast.success("Terms accepted — welcome to StoryMe! 🎉");
    navigate("/home", { replace: true });
  };

  // ── Decline ────────────────────────────────────────────────────────────────

  const handleDecline = async () => {
    setLoading(true);
    // Record the rejection so it can be audited; ignore errors — user is leaving anyway
    await acceptTerms(mobile, false).catch(() => {});
    setLoading(false);

    toast.error(
      "You must accept the Terms and Conditions to use StoryMe. You have been logged out.",
      { duration: 6000 }
    );
    navigate("/", { replace: true });
  };

  // ── scroll-to-bottom helper ────────────────────────────────────────────────

  const scrollToBottom = () => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  };

  // ─── render ───────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-purple-50 to-pink-50 flex items-center justify-center p-4">
      {/* Decorative background blobs */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-32 -left-32 w-96 h-96 rounded-full bg-indigo-200/30 blur-3xl" />
        <div className="absolute -bottom-24 -right-24 w-80 h-80 rounded-full bg-pink-200/30 blur-3xl" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-purple-100/20 blur-3xl" />
      </div>

      <div className="relative w-full max-w-2xl">
        {/* Header card */}
        <div className="bg-white/90 backdrop-blur-sm rounded-3xl shadow-2xl shadow-indigo-100/50 border border-white/60 overflow-hidden">
          {/* Top banner */}
          <div className="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 px-8 py-6">
            <div className="flex items-center gap-3 mb-2">
              <div className="bg-white/20 rounded-xl p-2">
                <Sparkles className="text-white" size={22} />
              </div>
              <div>
                <h1 className="text-xl font-bold text-white tracking-tight">StoryMe</h1>
                <p className="text-white/70 text-xs">Personalised Children's Storybooks</p>
              </div>
            </div>
            <h2 className="text-white text-2xl font-bold mt-3">Terms & Conditions</h2>
            <p className="text-white/80 text-sm mt-1">
              Please read carefully before using StoryMe.
            </p>
          </div>

          {/* Effective date */}
          <div className="px-8 py-3 bg-indigo-50/50 border-b border-indigo-100/60 flex items-center justify-between">
            <p className="text-xs text-slate-500">
              Effective: April 24, 2026 &nbsp;·&nbsp; Version 1.0
            </p>
            {!hasScrolledToBottom && (
              <button
                onClick={scrollToBottom}
                className="flex items-center gap-1 text-xs text-indigo-500 hover:text-indigo-700 transition-colors"
              >
                Scroll to read all <ChevronDown size={13} />
              </button>
            )}
            {hasScrolledToBottom && (
              <span className="flex items-center gap-1 text-xs text-emerald-600 font-medium">
                <CheckCircle2 size={13} /> Read ✓
              </span>
            )}
          </div>

          {/* Scrollable T&C body */}
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="overflow-y-auto px-6 py-5"
            style={{ maxHeight: "52vh" }}
          >
            {/* Key highlights callout */}
            <div className="rounded-2xl bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-200 p-5 mb-5">
              <p className="text-sm font-semibold text-amber-800 mb-3 flex items-center gap-2">
                <Shield size={16} className="text-amber-600" />
                Key Privacy Commitments
              </p>
              <ul className="space-y-2 text-sm text-amber-700">
                <li className="flex items-start gap-2">
                  <CheckCircle2 size={14} className="mt-0.5 text-amber-500 flex-shrink-0" />
                  Your child's photo is used <strong>only</strong> to generate the storybook character — nothing else.
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 size={14} className="mt-0.5 text-amber-500 flex-shrink-0" />
                  Images are stored securely for <strong>caching only</strong>, to avoid wasting resources on repeated processing.
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 size={14} className="mt-0.5 text-amber-500 flex-shrink-0" />
                  A cartoonised version of the photo <strong>will appear on the cover page</strong> of the generated storybook.
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 size={14} className="mt-0.5 text-amber-500 flex-shrink-0" />
                  Your image is <strong>never sold, shared, or used to train AI models</strong>.
                </li>
              </ul>
            </div>

            {SECTIONS.map((section, i) => (
              <SectionCard key={i} section={section} index={i} />
            ))}

            {/* Contact footer */}
            <div className="rounded-2xl bg-slate-50 border border-slate-100 p-4 mt-2 text-center">
              <p className="text-xs text-slate-500">
                Questions? Contact us at{" "}
                <span className="text-indigo-600 font-medium">legal@storyme.app</span>
                {" "}·{" "}
                <span className="text-indigo-600 font-medium">privacy@storyme.app</span>
              </p>
            </div>
          </div>

          {/* Footer — action buttons */}
          <div className="px-6 py-5 bg-white/80 border-t border-slate-100">
            {!hasScrolledToBottom && (
              <p className="text-center text-xs text-slate-400 mb-3">
                Scroll to the bottom to enable the Accept button
              </p>
            )}

            <div className="flex flex-col sm:flex-row gap-3">
              {/* Decline */}
              <Button
                variant="outline"
                onClick={handleDecline}
                disabled={loading}
                className="flex-1 border-red-200 text-red-600 hover:bg-red-50 hover:border-red-300 rounded-xl h-12"
              >
                {loading ? (
                  <Loader2 size={16} className="animate-spin mr-2" />
                ) : (
                  <XCircle size={16} className="mr-2" />
                )}
                Decline
              </Button>

              {/* Accept */}
              <Button
                onClick={handleAccept}
                disabled={!hasScrolledToBottom || loading}
                className={[
                  "flex-[2] rounded-xl h-12 font-semibold transition-all",
                  hasScrolledToBottom
                    ? "bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white shadow-lg shadow-indigo-200/50"
                    : "bg-slate-100 text-slate-400 cursor-not-allowed",
                ].join(" ")}
              >
                {loading ? (
                  <Loader2 size={16} className="animate-spin mr-2" />
                ) : (
                  <CheckCircle2 size={16} className="mr-2" />
                )}
                I Accept the Terms & Conditions
              </Button>
            </div>

            <p className="text-center text-xs text-slate-400 mt-3">
              By clicking Accept, you confirm you have read and understood all terms above.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
