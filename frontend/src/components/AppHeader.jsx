/**
 * AppHeader.jsx — Shared header for all protected StoryMe pages.
 *
 * Renders the StoryMe brand (BookOpen + title + Sparkles) on the left
 * and a user avatar trigger on the right that opens UserAccountSheet.
 *
 * Usage (drop-in replacement for the inline header each page used to have):
 *   import AppHeader from "@/components/AppHeader";
 *   // At the top of the page's returned JSX:
 *   <AppHeader />
 *
 * No props required — reads mobile from sessionStorage via getMobile().
 */

import { useState } from "react";
import { BookOpen, Sparkles, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getMobile } from "@/lib/session";
import UserAccountSheet from "@/components/UserAccountSheet";

export default function AppHeader() {
  const [sheetOpen, setSheetOpen] = useState(false);

  // Display just the last 5 digits of the mobile so the header stays compact
  const mobile  = getMobile() || "";
  const display = mobile ? `•••• ${mobile.slice(-5)}` : "Account";

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        {/* ── Brand ──────────────────────────────────────────────── */}
        <div className="flex items-center gap-2">
          <BookOpen className="w-9 h-9 text-emerald-600" />
          <h1 className="text-4xl font-bold text-gray-900 tracking-tight">StoryMe</h1>
          <Sparkles className="w-7 h-7 text-amber-500" />
        </div>

        {/* ── User trigger ───────────────────────────────────────── */}
        <button
          onClick={() => setSheetOpen(true)}
          aria-label="Open My Account"
          className="flex items-center gap-2 px-3 py-2 rounded-full
            bg-white border border-gray-200 shadow-sm
            hover:border-emerald-400 hover:shadow-md
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400
            transition-all duration-150 group"
        >
          <div className="w-7 h-7 rounded-full bg-emerald-100 flex items-center justify-center
            group-hover:bg-emerald-200 transition-colors">
            <User className="w-4 h-4 text-emerald-600" />
          </div>
          <span className="text-xs text-gray-500 font-medium hidden sm:block">{display}</span>
        </button>
      </div>

      <UserAccountSheet open={sheetOpen} onOpenChange={setSheetOpen} />
    </>
  );
}
