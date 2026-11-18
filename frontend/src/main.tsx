import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "@fontsource-variable/inter";
import "./styles.css";
import { Toaster } from "./backoffice/ui";
import { ErrorBoundary } from "./ErrorCard";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
    <Toaster />
  </React.StrictMode>,
);
