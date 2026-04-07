import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";
import { Toaster } from "@/components/ui/sonner";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
    {/*
      Toaster is rendered outside <BrowserRouter> intentionally —
      it is a portal that attaches to document.body and does not
      need routing context.
    */}
    <Toaster position="top-right" richColors closeButton />
  </React.StrictMode>,
);
