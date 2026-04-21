/**
 * PrintProductCard.jsx
 * --------------------
 * Displays a single print product option (paperback or hardcover).
 * Shows front + back cover images, price, description, and a select radio.
 *
 * Props:
 *   product      — product object from /api/v2/print/products
 *   selected     — boolean, whether this card is selected
 *   onSelect     — callback(product_id) when card or radio clicked
 *   backendUrl   — base backend URL for cover image src
 */

import { Badge } from "@/components/ui/badge";
import { BookOpen, Star } from "lucide-react";

const COVER_ICONS = {
  paperback: "📖",
  hardcover: "📚",
};

const COVER_ACCENT = {
  paperback: "emerald",
  hardcover: "amber",
};

export default function PrintProductCard({ product, selected, onSelect, backendUrl }) {
  if (!product) return null;

  const accent   = COVER_ACCENT[product.cover_type] || "emerald";
  const icon     = COVER_ICONS[product.cover_type]  || "📖";
  const frontUrl = `${backendUrl}${product.cover_image_urls?.front || ""}`;
  const backUrl  = `${backendUrl}${product.cover_image_urls?.back  || ""}`;

  const borderClass = selected
    ? `border-2 border-${accent}-500 shadow-lg ring-2 ring-${accent}-200`
    : "border-2 border-gray-200 hover:border-gray-300 shadow-sm";

  return (
    <div
      className={`rounded-xl bg-white cursor-pointer transition-all duration-200 ${borderClass}`}
      onClick={() => onSelect(product.product_id)}
      role="radio"
      aria-checked={selected}
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") onSelect(product.product_id); }}
    >
      {/* Header */}
      <div className={`flex items-center justify-between px-4 pt-4 pb-2`}>
        <div className="flex items-center gap-2">
          <span className="text-xl">{icon}</span>
          <div>
            <h3 className="font-bold text-gray-800 text-sm leading-tight">
              {product.display_name}
            </h3>
            <p className="text-xs text-gray-500">{product.dimensions}</p>
          </div>
        </div>
        <div className="text-right">
          <p className={`text-xl font-black text-${accent}-600`}>
            {product.price_display}
          </p>
          <Badge variant="outline" className="text-xs mt-0.5">
            {product.cover_type === "hardcover" ? "Premium" : "Standard"}
          </Badge>
        </div>
      </div>

      {/* Cover images — front and back side by side */}
      <div className="px-4 py-3">
        <p className="text-xs text-gray-400 uppercase tracking-wide mb-2 font-medium">
          Cover Preview
        </p>
        <div className="flex gap-3">
          {/* Front cover */}
          <div className="flex-1">
            <p className="text-xs text-gray-500 mb-1 text-center">Front</p>
            <div className="rounded-lg overflow-hidden border border-gray-100 bg-gray-50 shadow-sm"
                 style={{ aspectRatio: "2/3" }}>
              <img
                src={frontUrl}
                alt={`${product.display_name} front cover`}
                className="w-full h-full object-cover"
                onError={(e) => {
                  e.target.style.display = "none";
                  e.target.parentElement.classList.add("flex","items-center","justify-center");
                  e.target.parentElement.innerHTML =
                    `<span class="text-gray-400 text-xs text-center p-2">Cover<br/>loading…</span>`;
                }}
              />
            </div>
          </div>
          {/* Back cover */}
          <div className="flex-1">
            <p className="text-xs text-gray-500 mb-1 text-center">Back</p>
            <div className="rounded-lg overflow-hidden border border-gray-100 bg-gray-50 shadow-sm"
                 style={{ aspectRatio: "2/3" }}>
              <img
                src={backUrl}
                alt={`${product.display_name} back cover`}
                className="w-full h-full object-cover"
                onError={(e) => {
                  e.target.style.display = "none";
                  e.target.parentElement.classList.add("flex","items-center","justify-center");
                  e.target.parentElement.innerHTML =
                    `<span class="text-gray-400 text-xs text-center p-2">Cover<br/>loading…</span>`;
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Description */}
      <div className="px-4 pb-3">
        <p className="text-xs text-gray-600 leading-relaxed">{product.description}</p>
        <div className="flex flex-wrap gap-2 mt-2">
          <Badge variant="secondary" className="text-xs">{product.pages} pages</Badge>
          <Badge variant="secondary" className="text-xs">Full colour</Badge>
          <Badge variant="secondary" className="text-xs">{product.paper_size}</Badge>
        </div>
      </div>

      {/* Select indicator */}
      <div className={`mx-4 mb-4 rounded-lg py-2.5 text-center text-sm font-semibold transition-colors
        ${selected
          ? `bg-${accent}-500 text-white`
          : "bg-gray-100 text-gray-500 hover:bg-gray-200"
        }`}>
        {selected ? `✓ Selected` : "Select this option"}
      </div>
    </div>
  );
}
